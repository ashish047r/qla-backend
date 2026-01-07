import requests
import logging
from datetime import datetime, date
from urllib.parse import urlparse, parse_qs

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.permissions import IsAuthenticated

from django.contrib.auth.models import User

from .models import Company, IpInfo
from accounts.models import UserProfile

logger = logging.getLogger(__name__)


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

