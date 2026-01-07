import logging
from urllib.parse import urlparse, parse_qs
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from rest_framework.response import Response
from django.contrib.auth.models import User

from .models import Company, CompanyVisit
from accounts.models import UserProfile
from .utils import create_company, create_company_visit, append_company_visit

logger = logging.getLogger(__name__)


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


class TestWebhookView(APIView):
    def post(self, request):
        print(request.data)
        return Response({"message": "Test webhook endpoint is operational." }, status=200)

