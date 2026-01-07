import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.permissions import IsAuthenticated

from django.conf import settings
from django.http import HttpResponseForbidden

from .models import Company, CompanyVisit
from .cron import update_conversion_status

logger = logging.getLogger(__name__)

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
