from unicodedata import category
import requests
import pytz
import os
import json
import uuid
import logging
import urllib.parse
from uuid import uuid4

from datetime import datetime, date
from urllib.parse import urlparse, parse_qs

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.permissions import IsAuthenticated

from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.http import HttpResponseForbidden
from django.utils.dateparse import parse_datetime
from django.contrib.auth.models import User

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.protobuf.json_format import MessageToDict

from google.ads.googleads.v22.enums.types.conversion_action_category import (
    ConversionActionCategoryEnum,
)

# `partial_failure_error_to_google_ads_failure` is not present in some google-ads versions.
try:
    from google.ads.googleads.errors import partial_failure_error_to_google_ads_failure  # type: ignore
except ImportError:  # pragma: no cover
    def partial_failure_error_to_google_ads_failure(status_error):
        return None

from .models import Company, IpInfo, CompanyVisit
from accounts.models import UserProfile
from google_ads.models import GoogleAdsProject
from .cron import update_conversion_status

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_SECRET_PATH = settings.GOOGLE_CLIENT_SECRET_PATH
GOOGLE_CLIENT_ID = settings.GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET = settings.GOOGLE_CLIENT_SECRET
GOOGLE_DEVELOPER_TOKEN = settings.GOOGLE_DEVELOPER_TOKEN

CRON_SECRET = settings.CRON_SECRET_KEY

class ConversionStatusCronView(APIView):
    # No auth. Lambda will authenticate using the custom header.
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        incoming = request.headers.get("X-CRON-KEY")
        expected = CRON_SECRET

        if not incoming or incoming != expected:
            logger.warning("Cron access denied: missing/invalid key from %s", request.META.get("REMOTE_ADDR"))
            return HttpResponseForbidden("Invalid cron key")

        try:
            result = update_conversion_status()
            logger.info("Cron processed conversion statuses: %s", result)
            return Response(
                {"status": result},
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.exception("Cron failed while updating conversion statuses")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class GetCompanyVisitDataView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user

        clid = request.query_params.get("clid")
        ad_type = request.query_params.get("ad_type")

        # Validate required params
        if not clid or not ad_type:
            return Response(
                {"error": "clid and ad_type are required query parameters"},
                status=400
            )

        # Filter companies for this user
        companies = Company.objects.filter(user=user, click_id=clid, ad_type=ad_type)

        if not companies.exists():
            return Response(
                {"error": "Company not found for user"},
                status=404
            )

        companies_with_visits = []

        for company in companies:
            visits = (
                CompanyVisit.objects.filter(company=company)
                .order_by("-timestamp")
                .values(
                    "event_name",
                    "user_agent",
                    "device_type",
                    "url_visited",
                    "timestamp",
                )
            )

            companies_with_visits.append({
                "company_name": company.company_name,
                "click_id": company.click_id,
                "ad_type": company.ad_type,
                "company_visits": list(visits),
            })

        return Response({"companies": companies_with_visits}, status=200)

class VerifyPixelView(APIView):
    def get(self, request):
        pixel_id = request.query_params.get('pixel_id')

        if not pixel_id:
            return Response({'error': 'Missing pixel_id.'}, status=400)

        try:
            user_profile = UserProfile.objects.get(pixel_id=pixel_id)
        except UserProfile.DoesNotExist:
            return Response({'success': False, 'company_domains': "", 'message': 'Pixel not found.'})

        try:
            return Response({'success': True,  'message': 'Pixel detected.', 'company_domains': user_profile.company_domains})
        except Exception as e:
            print("Error verifying pixel:", e)
            return Response({'success': False, 'company_domains': user_profile.company_domains, 'error': "Could not verify pixel."}, status=200)

class GetVisitDataView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user
        user_obj = User.objects.get(id=user.id)
        user_profile = UserProfile.objects.get(user=user_obj)

        # Retrieve optional start_date and end_date query params
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        ad_type = request.query_params.get('ad_type', "None")

        if ad_type == "google_ads":
            visits_qs = Company.objects.filter(user=user_obj, ad_type="google_ads")
        elif ad_type == "facebook_ads":
            visits_qs = Company.objects.filter(user=user_obj, ad_type="facebook_ads")
        else:
            visits_qs = Company.objects.filter(user=user_obj)

        # If both start_date and end_date are provided, filter Company timestamps
        if start_date and end_date:
            try:
                # Convert string dates to date objects, assuming YYYY-MM-DD format
                start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
                visits_qs = visits_qs.filter(timestamp__date__range=[start_date_obj, end_date_obj])
            except Exception as e:
                return Response({'error': 'Invalid date format. Should be YYYY-MM-DD.'}, status=400)
        
        visits_list_raw = list(visits_qs.values(
            'company_name', 'domain', 'url_visited', 'employees', 'revenue', 
            'timestamp', 'logo_url', 'utm_source', 'utm_medium', 'utm_content', 'utm_id', 'utm_term', 
            'utm_campaign', 'click_id', 'ad_type', 'ip_address','conversion_status'
        ))

        seen_click_ids = set()
        visits_list = []
        for visit in visits_list_raw:
            click_id = visit.get('click_id')
            if click_id not in seen_click_ids:
                seen_click_ids.add(click_id)
                visits_list.append(visit)

        return Response({'success': True, 'visits': visits_list}, status=200)

class OldSendVisitDataView(APIView):
    def post(self, request):
        pixel_id = request.data.get('id')
        if not pixel_id:
            return Response({'error': 'Missing pixel_id.'}, status=400)

        user_profile = UserProfile.objects.get(pixel_id=pixel_id)
        user_obj = user_profile.user

        url_visited = request.data.get('url')
        ip = request.data.get('ip')

        if not url_visited:
            return Response({'error': 'Missing URL.'}, status=400)
        if not ip:
            return Response({'error': 'Missing IP.'}, status=400)

        parsed_url = urlparse(url_visited)
        root_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
        query_params = parse_qs(parsed_url.query)

        click_id = query_params.get('gclid', ["null"])[0]
        if click_id == "null":
            click_id = query_params.get('fbclid', ["null"])[0]
            ad_type = "facebook_ads"
        else:
            ad_type = "google_ads"

        ip_info = IpInfo.objects.filter(ip_address=ip, status="Found")
        if ip_info.exists():
            ip_info = ip_info.first()
            as_name = ip_info.company_name
            as_domain = ip_info.domain
            confidence_score = ip_info.confidence_score
            print("Stored IP info found for ip", ip)
        else:
            print("No stored IP info found for ip", ip)
            headers = {
                "Content-Type": "application/json",
                "X-API-KEY": f"CLVSzwpdAD6Fv0tr54dFDaLXsgAGAPnG5LItcuuf"
            }
            ipinfo_resp = requests.get(f'https://api.lf-discover.com/companies?ip={ip}', headers=headers)

            if ipinfo_resp.status_code != 200:
                IpInfo.objects.create(ip_address=ip, status="Not Found", domain=url_visited, company_name=user_profile.company_name, confidence_score="", click_id=click_id)
                return False
            ipinfo_data = ipinfo_resp.json()
            as_name = ipinfo_data.get("company")["name"]
            as_domain = ipinfo_data.get("company")["domain"]
            country_code = ipinfo_data.get("location")["country_code"]
 
            confidence_score = ipinfo_data.get("confidence_score")
            IpInfo.objects.create(ip_address=ip, company_name=as_name, domain=as_domain, confidence_score=confidence_score, status="Found", click_id=click_id)

        print("url_visited", url_visited)
        print("as_name", as_name)
        print("as_domain", as_domain)
        print("ip", ip)
        print("confidence_score", confidence_score)

        utm_source = query_params.get('utm_source', ["null"])[0]
        utm_medium = query_params.get('utm_medium', ["null"])[0]
        utm_content = query_params.get('utm_content', ["null"])[0]
        utm_id = query_params.get('utm_id', ["null"])[0]
        utm_term = query_params.get('utm_term', ["null"])[0]
        utm_campaign = query_params.get('utm_campaign', ["null"])[0]

        domain = root_url

        companyenrich_api_key = 'F0nyDGCBOfKKntUYWek9vO'
        url = "https://api.companyenrich.com/companies/enrich?domain=" + as_domain

        headers = {
            "accept": "application/json",
            "Authorization": "Bearer " + companyenrich_api_key
        }

        response = requests.get(url, headers=headers)

        logo_url = response.json().get('logo_url')
        company_name = response.json().get('name')
        website = response.json().get('website')
        url_visited = request.data.get('url')
        employees = response.json().get('employees')
        revenue = response.json().get('revenue')

        print("company_name", company_name)
        print("website", website)

        count = Company.objects.filter(user=user_obj).count()

        # Check if a Company with this company_name exists for today
        today = date.today()
        existing_visit = Company.objects.filter(
            company_name=company_name,
            timestamp__date=today
        ).exists()

        company_visit = Company.objects.create(
            user=user_obj,
            logo_url=logo_url,
            company_name=company_name,
            domain=website,
            url_visited=url_visited,
            employees=employees,
            revenue=revenue,
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_content=utm_content,
            utm_id=utm_id,
            utm_term=utm_term,
            utm_campaign=utm_campaign,
            click_id=click_id,
            ad_type=ad_type,
            confidence_score=confidence_score,
            ip_address=ip,
            country_code=country_code,
        )

        return Response({"success": True}, status=200)

class SendVisitDataView(APIView):
    def post(self, request):
        pixel_id = request.data.get('id')
        if not pixel_id:
            return Response({'error': 'Missing pixel_id.'}, status=400)

        user_profile = UserProfile.objects.get(pixel_id=pixel_id)
        user_obj = user_profile.user

        url_visited = request.data.get('url')
        ip = request.data.get('ip')

        if not url_visited:
            return Response({'error': 'Missing URL.'}, status=400)
        if not ip:
            return Response({'error': 'Missing IP.'}, status=400)

        parsed_url = urlparse(url_visited)
        root_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
        query_params = parse_qs(parsed_url.query)

        click_id = query_params.get('gclid', ["null"])[0]
        if click_id == "null":
            click_id = query_params.get('fbclid', ["null"])[0]
            ad_type = "facebook_ads"
        else:
            ad_type = "google_ads"

        logo_url = None
        employees = None
        revenue = None
        country_code = None

        headers = {
            "Authorization": f"Bearer 512|3Mh7A3c0kwMBNskFzNOTXLulrQ770lpXtyoqj7ayc4969073",
            "Accept": "application/json",
        }

        try:
            snitcher_resp = requests.post(
                f"https://api.snitcher.com/company/find?ip={ip}",
                headers=headers,
                timeout=10,
            )
        except Exception as exc:
            logger.exception("Snitcher API request failed")
            return Response({"error": "Failed to reach Snitcher API."}, status=status.HTTP_502_BAD_GATEWAY)

        if snitcher_resp.status_code == 202:
            return Response({"error": "Enrichment queued. Please retry shortly."}, status=status.HTTP_202_ACCEPTED)
        if snitcher_resp.status_code == 404:
            IpInfo.objects.create(
                ip_address=ip,
                status="Not Found",
                domain=root_url,
                company_name=user_profile.company_name,
                click_id=click_id,
            )
            return Response({"error": "Company not identified for this IP."}, status=status.HTTP_404_NOT_FOUND)
        if snitcher_resp.status_code != 200:
            logger.warning("Snitcher lookup failed: %s %s", snitcher_resp.status_code, snitcher_resp.text)
            return Response({"error": "Failed to identify company for IP."}, status=snitcher_resp.status_code)

        snitcher_data = snitcher_resp.json()
        company_data = snitcher_data.get("company") or {}

        company_name = company_data.get("name") or company_data.get("domain") or snitcher_data.get("domain") or user_profile.company_name
        domain = company_data.get("website") or company_data.get("domain") or snitcher_data.get("domain") or root_url
        employees = company_data.get("employee_range")
        revenue = company_data.get("annual_revenue")
        geo_data = snitcher_data.get("geoIP") or {}
        country_code = geo_data.get("country_code")

        companyenrich_api_key = 'F0nyDGCBOfKKntUYWek9vO'
        url = "https://api.companyenrich.com/companies/enrich?domain=" + domain

        headers = {
            "accept": "application/json",
            "Authorization": "Bearer " + companyenrich_api_key
        }

        response = requests.get(url, headers=headers)

        logo_url = response.json().get('logo_url')

        IpInfo.objects.create(
            ip_address=ip,
            company_name=company_name,
            domain=domain,
            status="Found",
            click_id=click_id,
        )

        print("url_visited", url_visited)
        print("company_name", company_name)
        print("domain", domain)
        print("ip", ip)

        utm_source = query_params.get('utm_source', ["null"])[0]
        utm_medium = query_params.get('utm_medium', ["null"])[0]
        utm_content = query_params.get('utm_content', ["null"])[0]
        utm_id = query_params.get('utm_id', ["null"])[0]
        utm_term = query_params.get('utm_term', ["null"])[0]
        utm_campaign = query_params.get('utm_campaign', ["null"])[0]

        count = Company.objects.filter(user=user_obj).count()

        # Check if a Company with this company_name exists for today
        today = date.today()
        existing_visit = Company.objects.filter(
            company_name=company_name,
            timestamp__date=today
        ).exists()

        company_visit = Company.objects.create(
            user=user_obj,
            logo_url=logo_url,
            company_name=company_name,
            domain=domain,
            url_visited=url_visited,
            employees=employees,
            revenue=revenue,
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_content=utm_content,
            utm_id=utm_id,
            utm_term=utm_term,
            utm_campaign=utm_campaign,
            click_id=click_id,
            ad_type=ad_type,
            ip_address=ip,
            country_code=country_code,
        )

        return Response({"success": True}, status=200)

class VisitToGoogleAdsConversionView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    def post(self, request):
        user = request.user
        user_obj = User.objects.get(id=user.id)
        user_profile = UserProfile.objects.get(user=user_obj)

        data = request.data["conversions"]

        gt_obj = GoogleAdsProject.objects.filter(user = user_obj).last()
        refresh_token = gt_obj.refresh_token
        customer_id = gt_obj.customer_id
        manager_id = gt_obj.manager_id
        GOOGLE_LOGIN_CUSTOMER_ID = manager_id

        # Configure using dictionary.
        credentials = {
            "developer_token": GOOGLE_DEVELOPER_TOKEN,
            "refresh_token": refresh_token,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "login_customer_id": GOOGLE_LOGIN_CUSTOMER_ID,
            "use_proto_plus": True
        }

        googleads_client = GoogleAdsClient.load_from_dict(credentials)

        for conversion in data:
            gclid = conversion["click_id"]
            conversion_value = conversion["conversion_value"]

            try:
                company_visit_obj = Company.objects.get(click_id=gclid)
            except Company.DoesNotExist:
                print("Company visit object not found for gclid", gclid)
                continue

            try:
                conversion_value_float = float(conversion_value)
            except (TypeError, ValueError):
                conversion_value_float = 1.0

            conversion_time = company_visit_obj.timestamp
            if conversion_time.tzinfo is None or conversion_time.tzinfo.utcoffset(conversion_time) is None:
                conversion_time = pytz.UTC.localize(conversion_time)
            else:
                conversion_time = conversion_time.astimezone(pytz.UTC)

            conversion_time = conversion_time.replace(microsecond=0)
            offset = conversion_time.strftime("%z")
            offset_formatted = f"{offset[:-2]}:{offset[-2:]}" if offset else "+00:00"
            conversion_time = f"{conversion_time.strftime('%Y-%m-%d %H:%M:%S')}{offset_formatted}"

            event_data = upload_conversion_event(
                googleads_client,
                customer_id,
                gt_obj.conversion_action_resource_name,
                gclid,
                conversion_time,
                conversion_value_float,
            )

            if not event_data["success"]:
                print ("Error uploading conversion event for gclid", gclid, event_data["message"])
            else:
                print ("Successfully uploaded conversion event for gclid", gclid)
                company_visit_obj.conversion_status = "Sent"
                company_visit_obj.save()

        return Response({'success': True}, status=200)

class VisitToFacebookAdsConversionView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    def post(self, request):
        user = request.user
        user_obj = User.objects.get(id=user.id)
        user_profile = UserProfile.objects.get(user=user_obj)

        data = request.data["conversions"]

        gt_obj = GoogleAdsProject.objects.filter(user = user_obj).last()
        refresh_token = gt_obj.refresh_token
        customer_id = gt_obj.customer_id

        GOOGLE_LOGIN_CUSTOMER_ID = "1087287060"

        # Configure using dictionary.
        credentials = {
            "developer_token": GOOGLE_DEVELOPER_TOKEN,
            "refresh_token": refresh_token,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "login_customer_id": GOOGLE_LOGIN_CUSTOMER_ID,
            "use_proto_plus": True
        }

        return Response({'success': True}, status=200)

        googleads_client = GoogleAdsClient.load_from_dict(credentials)

        for conversion in data:
            fbclid = conversion.get('fbclid')
            conversion_time = conversion.get('company_name')
            conversion_value = conversion.get('conversion_value')

            conversion_resource_name = get_or_create_custom_conversion(googleads_client, customer_id, "GS ICP Company Visit")

            upload_conversion_event(googleads_client, customer_id, conversion_resource_name, gclid)

        return Response({'success': True}, status=200)

def create_google_ads_custom_conversion(
    client: GoogleAdsClient,
    customer_id: str,
    conversion_name: str,
    category_name: str,
) -> dict:
    conversion_action_service = client.get_service("ConversionActionService")
    ga_service = client.get_service("GoogleAdsService")

    conversion_action_status_enum = client.enums.ConversionActionStatusEnum
    conversion_action_type_enum = client.enums.ConversionActionTypeEnum
    conversion_action_category_enum = client.enums.ConversionActionCategoryEnum

    # Validate category
    try:
        category_enum_value = conversion_action_category_enum[category_name]
    except KeyError:
        raise ValueError(
            f"Invalid conversion category '{category_name}'. "
            f"Must be one of: {list(conversion_action_category_enum.__members__.keys())}"
        )

    # Check if conversion already exists by name
    query = f"""
        SELECT
            conversion_action.resource_name,
            conversion_action.name,
            conversion_action.category
        FROM conversion_action
        WHERE conversion_action.name = '{conversion_name}'
        AND conversion_action.status != 'REMOVED'
    """

    response = ga_service.search_stream(customer_id=customer_id, query=query)

    for batch in response:
        for row in batch.results:
            existing_category = conversion_action_category_enum.ConversionActionCategory(
                row.conversion_action.category
            ).name

            return {
                "resource_name": row.conversion_action.resource_name,
                "descriptive_name": row.conversion_action.name,
                "category_name": existing_category,
                "already_exists": True,
            }

    # ---- GUARANTEED NEW CONVERSION ----
    unique_name = f"{conversion_name} ({uuid4().hex[:6]})"

    operation = client.get_type("ConversionActionOperation")
    conversion_action = operation.create

    conversion_action.name = unique_name
    conversion_action.type_ = conversion_action_type_enum.UPLOAD_CLICKS
    conversion_action.status = conversion_action_status_enum.ENABLED
    conversion_action.category = category_enum_value

    # Secondary conversion (must be set ONLY on create)
    conversion_action.primary_for_goal = False

    response = conversion_action_service.mutate_conversion_actions(
        customer_id=customer_id,
        operations=[operation],
    )

    resource_name = response.results[0].resource_name

    return {
        "resource_name": resource_name,
        "descriptive_name": unique_name,
        "category_name": category_name,
        "already_exists": False,
    }

def upload_conversion_event(
    client: GoogleAdsClient,
    customer_id: str,
    conversion_action: str,
    gclid: str,
    conversion_date_time: str,
    conversion_value: float = 1.0,
    currency_code: str = "USD"
):
    try:
        conversion_upload_service = client.get_service("ConversionUploadService")

        print("--------------DETAILS OF CONVERSION EVENT------------------")
        print("gclid", gclid)
        print("conversion_action", conversion_action)
        print("conversion_date_time", conversion_date_time)
        print("conversion_value", conversion_value)
        print("currency_code", currency_code)
        print("customer_id", customer_id)
        print("--------------------------------")

        click_conversion = client.get_type("ClickConversion")
        click_conversion.conversion_action = conversion_action
        click_conversion.gclid = gclid
        click_conversion.conversion_date_time = conversion_date_time
        click_conversion.conversion_value = conversion_value
        click_conversion.currency_code = currency_code

        response = conversion_upload_service.upload_click_conversions(
            customer_id=customer_id,
            conversions=[click_conversion],
            partial_failure=True,
        )

        # Log the full response for debugging partial failures
        try:
            resp_proto = getattr(response, "_pb", response)
            resp_dict = MessageToDict(resp_proto, preserving_proto_field_name=True)
            print("Conversion upload response:", resp_dict)
        except Exception as exc:  # pragma: no cover
            print("Failed to serialize conversion upload response:", exc)

        status_error = response.partial_failure_error
        if status_error and (getattr(status_error, "code", None) or getattr(status_error, "details", [])):
            detailed_errors = []

            # Use helper to reliably unpack any partial failure errors
            failure = partial_failure_error_to_google_ads_failure(status_error)
            if failure and getattr(failure, "errors", None):
                for error in failure.errors:
                    code = error.error_code.WhichOneof("error_code")
                    code_value = getattr(error.error_code, code) if code else "UNKNOWN"
                    location_path = ""
                    if error.location:
                        location_path = ".".join(
                            element.field_name for element in error.location.field_path_elements
                        )
                    detailed_errors.append(
                        f"{code_value}: {error.message}"
                        + (f" (field: {location_path})" if location_path else "")
                    )

            for detail in status_error.details:
                failure_message = client.get_type("GoogleAdsFailure")
                try:
                    # Attempt to unpack Any into GoogleAdsFailure
                    detail.Unpack(failure_message)
                except Exception:
                    # Fallback to ParseFromString if Unpack is unavailable
                    failure_message.ParseFromString(detail.value)

                if getattr(failure_message, "errors", None):
                    for error in failure_message.errors:
                        code = error.error_code.WhichOneof("error_code")
                        code_value = getattr(error.error_code, code) if code else "UNKNOWN"
                        location_path = ""
                        if error.location:
                            location_path = ".".join(
                                element.field_name for element in error.location.field_path_elements
                            )
                        detailed_errors.append(
                            f"{code_value}: {error.message}"
                            + (f" (field: {location_path})" if location_path else "")
                        )
                else:
                    # If no errors parsed, log the raw detail for debugging
                    detailed_errors.append(str(MessageToDict(detail)))

            if detailed_errors:
                print("Partial failure details:", "; ".join(detailed_errors))

            status_proto = getattr(status_error, "_pb", status_error)
            status_dict = MessageToDict(status_proto, preserving_proto_field_name=True) if hasattr(status_proto, "DESCRIPTOR") else str(status_error)
            print("Partial failure status:", status_dict)
            print("Partial failure raw:", status_error)
            print("Partial failure repr:", repr(status_error))
            print("Partial failure details count:", len(getattr(status_error, "details", [])))
            print("Partial failure code attr:", getattr(status_error, "code", None))
            print("Partial failure message attr:", getattr(status_error, "message", None))

            message_text = status_dict.get("message") if isinstance(status_dict, dict) else ""
            code_text = status_dict.get("code") if isinstance(status_dict, dict) else ""
            fallback_code = getattr(status_error, "code", None)
            fallback_message = getattr(status_error, "message", "")

            combined_message = (
                "; ".join(detailed_errors)
                or message_text
                or (f"Partial failure code {code_text}" if code_text else "")
                or fallback_message
                or (f"Partial failure code {fallback_code}" if fallback_code else "")
                or str(status_error)
                or "Partial failure with empty status. See server logs for Conversion upload response."
                or "Unknown partial failure"
            )
            return {"success": False, "message": combined_message}

        print(f"Successfully uploaded conversion for GCLID {gclid}")
        return {"success": True, "message": f"Uploaded conversion for {gclid}"}

    except GoogleAdsException as ex:
        print("Google Ads API request failed with status:", ex.error.code().name)
        for error in ex.failure.errors:
            print("Error:", error.message)
        return {"success": False, "message": str(ex)}

class SetGoogleConversionEventView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        user = request.user
        user_obj = User.objects.get(id=user.id)
        user_profile = UserProfile.objects.get(user=user_obj)

        req_type = request.data["type"]
        resource_name = request.data["resource_name"]
        descriptive_name = request.data["descriptive_name"]
        category_name = request.data["category_name"]

        gt_obj = GoogleAdsProject.objects.filter(user=user_obj).last()
        if not gt_obj:
            return Response({'error': 'Google Ads project not found for user.'}, status=404)

        manager_id = gt_obj.manager_id
        GOOGLE_LOGIN_CUSTOMER_ID = manager_id

        credentials = {
            "developer_token": settings.GOOGLE_DEVELOPER_TOKEN,
            "refresh_token": gt_obj.refresh_token,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "login_customer_id": GOOGLE_LOGIN_CUSTOMER_ID,
            "use_proto_plus": True,
        }

        # Initialize Google Ads client with credentials
        googleads_client = GoogleAdsClient.load_from_dict(credentials)

        if req_type == "set":
            print("setting existing conversion action")
            gt_obj.conversion_action_resource_name = resource_name
            gt_obj.conversion_action_descriptive_name = descriptive_name
            gt_obj.conversion_action_category_name = category_name
            gt_obj.save()
 
            return Response({'success': True, 'resource_name': resource_name, 'descriptive_name': descriptive_name, 'category_name': category_name,}, status=200)

        elif req_type == "new":
            print("creating new conversion action")
            conversion_resource = create_google_ads_custom_conversion(googleads_client, gt_obj.customer_id, descriptive_name, category_name)
            gt_obj.conversion_action_resource_name = conversion_resource["resource_name"]
            gt_obj.conversion_action_descriptive_name = conversion_resource["descriptive_name"]
            gt_obj.conversion_action_category_name = conversion_resource["category_name"]
            gt_obj.save()

            return Response({'success': True, 'resource_name': conversion_resource["resource_name"], 'descriptive_name': conversion_resource["descriptive_name"], 'category_name': conversion_resource["category_name"]}, status=200)

        return Response({'success': False, 'resource_name': '', 'descriptive_name': ''}, status=400)

    def get(self, request):
        user = request.user
        user_obj = User.objects.get(id=user.id)

        # Get user's Google Ads project info
        gt_obj = GoogleAdsProject.objects.filter(user=user_obj).last()
        if not gt_obj:
            return Response(
                {'error': 'Google Ads project not found for user.'},
                status=404
            )

        refresh_token = gt_obj.refresh_token
        customer_id = gt_obj.customer_id
        manager_id = gt_obj.manager_id

        GOOGLE_LOGIN_CUSTOMER_ID = manager_id

        # Debug prints (yes, noisy, but useful)
        print("GOOGLE_LOGIN_CUSTOMER_ID", GOOGLE_LOGIN_CUSTOMER_ID)
        print("refresh_token", refresh_token)
        print("customer_id", customer_id)
        print("settings.GOOGLE_DEVELOPER_TOKEN", settings.GOOGLE_DEVELOPER_TOKEN)
        print("settings.GOOGLE_CLIENT_ID", settings.GOOGLE_CLIENT_ID)
        print("settings.GOOGLE_CLIENT_SECRET", settings.GOOGLE_CLIENT_SECRET)
        print("use_proto_plus", True)

        credentials = {
            "developer_token": settings.GOOGLE_DEVELOPER_TOKEN,
            "refresh_token": refresh_token,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "login_customer_id": GOOGLE_LOGIN_CUSTOMER_ID,
            "use_proto_plus": True,
        }

        # Initialize Google Ads client
        googleads_client = GoogleAdsClient.load_from_dict(credentials)
        ga_service = googleads_client.get_service("GoogleAdsService")

        # Query all non-removed conversion actions
        query = """
            SELECT
                conversion_action.resource_name,
                conversion_action.name,
                conversion_action.status,
                conversion_action.category
            FROM conversion_action
            WHERE conversion_action.status = 'ENABLED'
        """

        conversions = []
        selected_category = None

        try:
            response = ga_service.search_stream(
                customer_id=customer_id,
                query=query
            )

            for batch in response:
                for row in batch.results:
                    category_name = ConversionActionCategoryEnum.ConversionActionCategory(
                        row.conversion_action.category
                    ).name

                    conversions.append({
                        "resource_name": row.conversion_action.resource_name,
                        "descriptive_name": row.conversion_action.name,
                        "category_name": category_name,
                    })

                    # Match selected conversion to get its category
                    if (
                        row.conversion_action.resource_name
                        == gt_obj.conversion_action_resource_name
                    ):
                        selected_category = category_name

        except Exception as e:
            return Response(
                {'error': f'Error fetching conversions: {str(e)}'},
                status=500
            )

        conversion_event = {
            "conversion_action_resource_name": gt_obj.conversion_action_resource_name,
            "conversion_action_descriptive_name": gt_obj.conversion_action_descriptive_name,
            "category": selected_category,
        }

        return Response(
            {
                'success': True,
                'conversions': conversions,
                'conversion_event_selected': conversion_event,
            },
            status=200
        )

class SetFacebookConversionEventView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        user = request.user
        user_obj = User.objects.get(id=user.id)
        user_profile = UserProfile.objects.get(user=user_obj)

        req_type = request.data["type"]
        resource_name = request.data["resource_name"]
        descriptive_name = request.data["descriptive_name"]

        if req_type == "set":
            pass

        elif req_type == "new":
            pass

        return Response({'success': True, 'resource_name': resource_name, 'descriptive_name': descriptive_name}, status=200)

    def get(self, request):
        user = request.user
        user_obj = User.objects.get(id=user.id)

        # Get user's Google Ads project info
        gt_obj = GoogleAdsProject.objects.filter(user=user_obj).last()
        if not gt_obj:
            return Response({'error': 'Google Ads project not found for user.'}, status=404)

        refresh_token = gt_obj.refresh_token
        customer_id = gt_obj.customer_id

        GOOGLE_LOGIN_CUSTOMER_ID = "3641325870"
        print("GOOGLE_LOGIN_CUSTOMER_ID", GOOGLE_LOGIN_CUSTOMER_ID)
        print("refresh_token", refresh_token)
        print("customer_id", customer_id)
        print("settings.GOOGLE_DEVELOPER_TOKEN", settings.GOOGLE_DEVELOPER_TOKEN)
        print("settings.GOOGLE_CLIENT_ID", settings.GOOGLE_CLIENT_ID)
        print("settings.GOOGLE_CLIENT_SECRET", settings.GOOGLE_CLIENT_SECRET)
        print("use_proto_plus", True)

        credentials = {
            "developer_token": settings.GOOGLE_DEVELOPER_TOKEN,
            "refresh_token": refresh_token,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "login_customer_id": GOOGLE_LOGIN_CUSTOMER_ID,
            "use_proto_plus": True,
        }

        # Initialize Google Ads client with credentials
        googleads_client = GoogleAdsClient.load_from_dict(credentials)

        ga_service = googleads_client.get_service("GoogleAdsService")

        # Query to get all active (non-REMOVED) conversion actions
        query = """
            SELECT
                conversion_action.resource_name,
                conversion_action.name,
                conversion_action.status
            FROM conversion_action
            WHERE conversion_action.status != 'REMOVED'
        """

        response = ga_service.search_stream(customer_id=customer_id, query=query)

        conversions = []
        try:
            for batch in response:
                for row in batch.results:
                    conversions.append({
                        "resource_name": row.conversion_action.resource_name,
                        "descriptive_name": row.conversion_action.name,
                    })
        except Exception as e:
            return Response({'error': f'Error fetching conversions: {str(e)}'}, status=500)

        conversion_event = {"conversion_action_resource_name": gt_obj.conversion_action_resource_name, "conversion_action_descriptive_name": gt_obj.conversion_action_descriptive_name}

        return Response({'success': True, 'conversions': conversions, 'conversion_event_selected': conversion_event}, status=200)

class ListRadarPixel(APIView):
    def get(self, request):
        try:
            url = "https://api.snitcher.com/radar/operator/v1/tracking-scripts"
            headers = {
                "Authorization": "Bearer 511|E2434QIIwDUYauvxr0NsD37QWg01sfgU1vXuJo24849fb401"
            }

            external_response = requests.get(url, headers=headers)

            if external_response.status_code != 200:
                return Response(
                    {
                        "error": "Radar API returned a sad little failure",
                        "status_code": external_response.status_code,
                        "details": external_response.text,
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response(external_response.json(), status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": "Something exploded inside ListRadarPixel", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class RadarWebhookConfig(APIView):
    def patch(self, request):
        try:
            url = "https://api/snitcher.com/radar/operator/v1/webhooks"
            payload = {
                "delivery": {
                    "webhook_url": "https://qla-backend.zipeline.com/api/tracker/webhook/"
                }
            }
            headers = {
                "Authorization": "Bearer 511|E2434QIIwDUYauvxr0NsD37QWg01sfgU1vXuJo24849fb401",
                "Content-Type": "application/json"
            }

            external_response = requests.patch(url, json=payload, headers=headers)

            if external_response.status_code not in [200, 201]:
                return Response(
                    {
                        "error": "Radar API refused to cooperate",
                        "status_code": external_response.status_code,
                        "details": external_response.text
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response(external_response.json(), status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": "RadarWebhookConfig went sideways", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DeactivateRadarTracking(APIView):
    def patch(self, request):
        try:
            tracking_id = request.data.get("trackingScriptId")

            if not tracking_id:
                return Response(
                    {"error": "trackingScriptId is missing"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            url = f"https://api.snitcher.com/radar/operator/v1/tracking-scripts/{tracking_id}"

            # API expects a boolean, not the string "false"
            payload = {"active": False}

            headers = {
                "Authorization": "Bearer 511|E2434QIIwDUYauvxr0NsD37QWg01sfgU1vXuJo24849fb401",
                "Content-Type": "application/json"
            }

            external_response = requests.patch(url, json=payload, headers=headers)

            if external_response.status_code not in [200, 201]:
                return Response(
                    {
                        "error": "Failed to deactivate tracking script",
                        "status_code": external_response.status_code,
                        "details": external_response.text,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(external_response.json(), status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": "DeactivateRadarTracking malfunctioned", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class ActivateRadarTracking(APIView):
    def patch(self, request):
        try:
            tracking_id = request.data.get("trackingScriptId")

            if not tracking_id:
                return Response(
                    {"error": "trackingScriptId is missing"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            url = f"https://api.snitcher.com/radar/operator/v1/tracking-scripts/{tracking_id}"

            # API expects a boolean, not the string "true"
            payload = {"active": True}

            headers = {
                "Authorization": "Bearer 511|E2434QIIwDUYauvxr0NsD37QWg01sfgU1vXuJo24849fb401",
                "Content-Type": "application/json"
            }

            external_response = requests.patch(url, json=payload, headers=headers)

            if external_response.status_code not in [200, 201]:
                return Response(
                    {
                        "error": "Failed to activate tracking script",
                        "status_code": external_response.status_code,
                        "details": external_response.text,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(external_response.json(), status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": "ActivateRadarTracking crashed inelegantly", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class FindCompanyByIP(APIView):
    def post(self, request):
        try:
            ip = request.data.get("ip")

            if not ip:
                return Response(
                    {"error": "ip is missing"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            url = f"https://api.snitcher.com/company/find?ip={ip}"

            headers = {
                "Authorization": "Bearer 512|3Mh7A3c0kwMBNskFzNOTXLulrQ770lpXtyoqj7ayc4969073",
                "Accept": "application/json"
            }

            external_response = requests.post(url, headers=headers)

            # 200 = company found
            if external_response.status_code == 200:
                return Response(external_response.json(), status=status.HTTP_200_OK)

            # 404 = company not found (NOT an error)
            if external_response.status_code == 404:
                return Response(
                    {
                        "company_found": False,
                        "details": external_response.json()
                    },
                    status=status.HTTP_200_OK
                )

            # Other failures
            return Response(
                {
                    "error": "Snitcher find-company failed",
                    "status_code": external_response.status_code,
                    "details": external_response.text
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:
            return Response(
                {"error": "FindCompanyByIP crashed", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# -------------------------------------------------------
# MAIN WEBHOOK ENDPOINT
# -------------------------------------------------------

@method_decorator(csrf_exempt, name='dispatch')
class GetPixelData(APIView):
    def post(self, request):
        logger.info("Incoming pixel webhook received")

        payload = request.data
        print("payload", payload)
        logger.debug("Webhook payload: %s", payload)
    
        parsed = extract_tracking_data(payload)

        if parsed:
            parsed["raw_payload"] = payload
            logger.info("Parsed tracking payload: %s", parsed)
            handle_company_visit(parsed)
        else:
            logger.warning("No data extracted from webhook")

        return Response(status=200)

# -------------------------------------------------------
# EXTRACT BASIC TRACKING DATA
# -------------------------------------------------------

def extract_tracking_data(payload):
    logger.info("Extracting tracking data")

    internal_id = payload.get("internal_identifier")
    events = payload.get("events", [])

    if not events:
        logger.warning("events array missing or empty in webhook")
        return None

    first_event = events[0]
    logger.debug("First event: %s", first_event)

    ip = (
        first_event.get("context", {})
        .get("geo", {})
        .get("ip")
    )

    page_url = (
        first_event.get("context", {})
        .get("page", {})
        .get("url")
    )

    clid = None
    ad_type = None

    if page_url:
        parsed = urlparse(page_url)
        qs = parse_qs(parsed.query)
        logger.debug("Parsed query params: %s", qs)

        if "gclid" in qs:
            clid = qs["gclid"][0]
            ad_type = "google_ads"
        elif "fbclid" in qs:
            clid = qs["fbclid"][0]
            ad_type = "facebook_ads"

    extracted = {
        "internal_identifier": internal_id,
        "ip": ip,
        "clid": clid,
        "ad_type": ad_type,
        "url": page_url
    }

    logger.info("Extracted data: %s", extracted)
    return extracted

# -------------------------------------------------------
# HANDLE COMPANY LOGIC
# -------------------------------------------------------

def handle_company_visit(result):
    logger.info("Handling company visit")

    internal_id = result.get("internal_identifier")
    ip_raw = result.get("ip")
    ip = ip_raw.strip() if isinstance(ip_raw, str) else ip_raw

    logger.debug("internal_id=%s, ip=%s", internal_id, ip)

    if not internal_id or not ip:
        logger.error("Missing internal_identifier or IP")
        return

    # Resolve user
    user = None
    try:
        user = User.objects.get(username=internal_id)
        logger.info("User resolved by username: %s", user)
    except User.DoesNotExist:
        try:
            user = User.objects.get(email=internal_id)
            logger.info("User resolved by email: %s", user)
        except User.DoesNotExist:
            logger.error("Unknown internal_identifier %s", internal_id)
            return

    # Pixel ID
    try:
        user_profile = UserProfile.objects.get(user=user)
        pixel_id = user_profile.pixel_id
        logger.info("Pixel ID resolved: %s", pixel_id)
    except UserProfile.DoesNotExist:
        pixel_id = None
        logger.warning("User profile missing")

    result["pixel_id"] = pixel_id

    # Existing company lookup
    company = Company.objects.filter(user=user, ip_address__iexact=ip).first()

    if company:
        logger.info("Existing company found for IP: %s", company.id)
        append_company_visit(company, result["raw_payload"])
        return

    # Create new company
    logger.info("No company found for IP, creating new one")
    company = create_company(result, user)

    if isinstance(company, Company):
        logger.info("Company created: %s", company.id)
        if CompanyVisit.objects.filter(company=company).exists():
            logger.info("Company already has visits; appending new ones instead of creating duplicates")
            append_company_visit(company, result["raw_payload"])
        else:
            create_company_visit(company, result["raw_payload"])
    else:
        logger.error("Company creation failed, result was: %s", company)

# -------------------------------------------------------
# CREATE COMPANY
# -------------------------------------------------------

def create_company(payload, user):
    logger.info("Creating company for user %s", user)

    try:
        user_profile = UserProfile.objects.get(user=user)
    except UserProfile.DoesNotExist:
        logger.error("User profile not found for user %s", user)
        return None

    url_visited = payload.get('url')
    ip_raw = payload.get('ip')
    ip = ip_raw.strip() if isinstance(ip_raw, str) else ip_raw

    if not url_visited or not ip:
        logger.error("Missing URL or IP for company creation")
        return None

    # Double-check existence here to avoid accidental duplicates in fast retries
    existing_company = Company.objects.filter(user=user, ip_address__iexact=ip).first()
    if existing_company:
        logger.info("Company already exists for IP %s (id=%s); reusing", ip, existing_company.id)
        return existing_company

    click_id = payload.get('clid') or "null"
    ad_type = payload.get('ad_type') or "unknown"

    parsed_url = urlparse(url_visited)
    query_params = parse_qs(parsed_url.query)

    root_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"

    logger.debug("Root URL: %s", root_url)
    logger.debug("Query params: %s", query_params)

    # Snitcher lookup
    headers = {
        "Authorization": "Bearer 512|3Mh7A3c0kwMBNskFzNOTXLulrQ770lpXtyoqj7ayc4969073",
        "Accept": "application/json",
    }

    logger.info("Calling Snitcher API for IP %s", ip)

    try:
        snitcher_resp = requests.post(
            f"https://api.snitcher.com/company/find?ip={ip}",
            headers=headers,
            timeout=10,
        )
    except requests.RequestException:
        logger.exception("Snitcher API request failed")
        return None

    logger.info("Snitcher response %s: %s", snitcher_resp.status_code, snitcher_resp.text)

    if snitcher_resp.status_code in [202, 404]:
        logger.warning("Snitcher did not return company data for IP %s", ip)
        # Always log the attempt in IpInfo, update if exists, else create
        ipinfo_obj, created = IpInfo.objects.get_or_create(
            ip_address=ip,
            defaults={
                "status": "Not Found",
                "domain": root_url,
                "company_name": user_profile.company_name,
                "click_id": click_id,
            }
        )
        if not created:
            # Update status and fill missing fields if needed
            ipinfo_obj.status = "Not Found"
            if not ipinfo_obj.domain:
                ipinfo_obj.domain = root_url
            if not ipinfo_obj.company_name:
                ipinfo_obj.company_name = user_profile.company_name
            if not ipinfo_obj.click_id:
                ipinfo_obj.click_id = click_id
            ipinfo_obj.save()
        return None

    if snitcher_resp.status_code != 200:
        logger.error("Unexpected Snitcher status %s", snitcher_resp.status_code)
        return None

    snitcher_data = snitcher_resp.json()
    logger.debug("Snitcher JSON: %s", snitcher_data)

    company_data = snitcher_data.get("company") or {}
    geo_data = snitcher_data.get("geoIP") or {}

    # -----------------------------
    # Geo fields from Snitcher
    # -----------------------------
    country = geo_data.get("country")
    country_code = geo_data.get("country_code")
    state = geo_data.get("state")
    city = geo_data.get("city")

    # -----------------------------
    # Additional enrichment fields
    # -----------------------------
    postal_code = geo_data.get("postal_code") or geo_data.get("zip")

    company_type = company_data.get("type")
    industry = company_data.get("industry")

    # Ensure list format for JSONFields
    categories = company_data.get("categories") or []
    keywords = company_data.get("keywords") or []
    technologies = company_data.get("technologies") or []

    # Defensive normalization (important)
    if not isinstance(categories, list):
        categories = [categories]

    if not isinstance(keywords, list):
        keywords = [keywords]

    if not isinstance(technologies, list):
        technologies = [technologies]

    company_name = (
        company_data.get("name")
        or company_data.get("domain")
        or snitcher_data.get("domain")
        or user_profile.company_name
    )

    domain = (
        company_data.get("website")
        or company_data.get("domain")
        or snitcher_data.get("domain")
        or root_url
    )

    employees = company_data.get("employee_range")
    revenue = company_data.get("annual_revenue")
    country_code = geo_data.get("country_code")

    # Enrich (logo)
    enrich_url = f"https://api.companyenrich.com/companies/enrich?domain={domain}"
    enrich_headers = {
        "accept": "application/json",
        "Authorization": "Bearer F0nyDGCBOfKKntUYWek9vO"
    }

    logger.info("Calling CompanyEnrich for domain %s", domain)

    try:
        enrich_resp = requests.get(enrich_url, headers=enrich_headers)

        enrich_data = enrich_resp.json()
        logger.debug("CompanyEnrich raw response: %s", enrich_data)

        logo_url = enrich_data.get("logo_url")

        # Optional enrichments (provider-dependent)
        technologies = enrich_data.get("technologies") or technologies
        categories = enrich_data.get("categories") or categories
        keywords = enrich_data.get("keywords") or keywords
        company_type = enrich_data.get("type") or company_type

        location = enrich_data.get("location") or {}

        postal_code = location.get("postal_code") or postal_code

        # Optional but more precise than IP-based geo
        country = (location.get("country") or {}).get("name") or country
        country_code = (location.get("country") or {}).get("code") or country_code
        state = (location.get("state") or {}).get("name") or state
        city = (location.get("city") or {}).get("name") or city

    except Exception:
        logger.exception("CompanyEnrich request failed")
        logo_url = None

    # Log lookup (deduplicated)
    ipinfo_obj, created = IpInfo.objects.get_or_create(
        ip_address=ip,
        defaults={
            "company_name": company_name,
            "domain": domain,
            "status": "Found",
            "click_id": click_id,
        }
    )
    if not created:
        # Update with enriched info if missing
        ipinfo_obj.company_name = company_name
        ipinfo_obj.domain = domain
        ipinfo_obj.status = "Found"
        ipinfo_obj.click_id = click_id
        ipinfo_obj.save()

    # Extract UTMs
    utm_source = query_params.get("utm_source", ["null"])[0]
    utm_medium = query_params.get("utm_medium", ["null"])[0]
    utm_content = query_params.get("utm_content", ["null"])[0]
    utm_id = query_params.get("utm_id", ["null"])[0]
    utm_term = query_params.get("utm_term", ["null"])[0]
    utm_campaign = query_params.get("utm_campaign", ["null"])[0]

    company = Company.objects.create(
        user=user,
        logo_url=logo_url,
        company_name=company_name,
        domain=domain,
        url_visited=url_visited,
        employees=employees,
        revenue=revenue,

        # NEW FIELDS
        postal_code=postal_code,
        company_type=company_type,
        industry=industry,
        categories=categories,
        keywords=keywords,
        technologies=technologies,
        country=country,
        state=state,
        city=city,

        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_content=utm_content,
        utm_id=utm_id,
        utm_term=utm_term,
        utm_campaign=utm_campaign,
        click_id=click_id,
        ad_type=ad_type,
        ip_address=ip,
        country_code=country_code,
    )
    print(company)

    logger.info("Company created with ID %s", company.id)

    return company

# -------------------------------------------------------
# CREATE VISIT RECORDS
# -------------------------------------------------------

def create_company_visit(company, payload):
    logger.info("Creating visits for company %s", company.id)

    events = payload.get("events", [])

    if not events:
        logger.warning("Visit creation skipped, no events")
        return

    for ev in events:
        ts = parse_datetime(ev.get("created_at"))

        if not ts:
            logger.warning("Skipping event with invalid timestamp: %s", ev)
            continue

        CompanyVisit.objects.create(
            company=company,
            event_name=ev.get("event_name", "unknown_event"),
            timestamp=ts,
            user_agent=ev.get("context", {}).get("user_agent", ""),
            device_type=ev.get("context", {}).get("device", {}).get("type", ""),
            url_visited=(
                ev.get("context", {}).get("page", {}).get("url")
                or ev.get("event_properties", {}).get("$url", "")
            ),
            event_properties=ev.get("event_properties", {}),
        )

        logger.debug("Visit created: %s", ev)

# -------------------------------------------------------
# APPEND ONLY NEWER VISITS
# -------------------------------------------------------

def append_company_visit(company, payload):
    logger.info("Appending new visits to company %s", company.id)

    events = payload.get("events", [])
    if not events:
        logger.warning("Append skipped, no events present")
        return

    last_visit = (
        CompanyVisit.objects.filter(company=company)
        .order_by("-timestamp")
        .first()
    )

    last_timestamp = last_visit.timestamp if last_visit else None
    logger.debug("Last saved visit timestamp: %s", last_timestamp)

    new_visits = []

    for ev in events:
        ts_str = ev.get("created_at")
        ts = parse_datetime(ts_str)

        if not ts:
            logger.warning("Skipping event with invalid timestamp: %s", ev)
            continue

        if last_timestamp and ts <= last_timestamp:
            logger.debug("Skipping older event at %s", ts)
            continue

        new_visits.append(
            CompanyVisit(
                company=company,
                event_name=ev.get("event_name", "unknown_event"),
                timestamp=ts,
                user_agent=ev.get("context", {}).get("user_agent", ""),
                device_type=ev.get("context", {}).get("device", {}).get("type", ""),
                url_visited=(
                    ev.get("context", {}).get("page", {}).get("url")
                    or ev.get("event_properties", {}).get("$url", "")
                ),
                event_properties=ev.get("event_properties", {}),
            )
        )

        logger.debug("New visit queued: %s", ev)

    if new_visits:
        CompanyVisit.objects.bulk_create(new_visits)
        logger.info("Appended %s new visits", len(new_visits))
    else:
        logger.info("No new visits to append")

class TestWebhookView(APIView):
    def post(self, request):
        print(request.data)
        return Response({"message": "Test webhook endpoint is operational." }, status=200)

class CreateCompanyView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Creates a Company using payload + enrichment logic
        """
        payload = request.data
        user = request.user

        company = create_company(payload, user)

        if not company:
            return Response(
                {"success": False, "message": "Company could not be created"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "success": True,
                "company_id": company.id,
                "company_name": company.company_name,
                "domain": company.domain,
            },
            status=status.HTTP_201_CREATED,
        )
