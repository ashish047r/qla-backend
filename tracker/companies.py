import requests
import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.permissions import IsAuthenticated

from .models import Company
from .utils import create_company

logger = logging.getLogger(__name__)


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

