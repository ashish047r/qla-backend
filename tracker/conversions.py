import pytz
import logging
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.models import User
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.permissions import IsAuthenticated

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

from .models import Company
from accounts.models import UserProfile
from google_ads.models import GoogleAdsProject

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = settings.GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET = settings.GOOGLE_CLIENT_SECRET
GOOGLE_DEVELOPER_TOKEN = settings.GOOGLE_DEVELOPER_TOKEN

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
