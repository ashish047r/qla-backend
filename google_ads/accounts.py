from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from google.ads.googleads.errors import GoogleAdsException

from .models import GoogleAdsProject
from .services.google_ads_client import build_client

GOOGLE_CLIENT_ID = settings.GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET = settings.GOOGLE_CLIENT_SECRET
GOOGLE_DEVELOPER_TOKEN = settings.GOOGLE_DEVELOPER_TOKEN


class ListClientsView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response(
                {"detail": "Valid access token required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        gt_obj = GoogleAdsProject.objects.get(user=user)
        refresh_token = gt_obj.refresh_token

        try:
            client = build_client(
                refresh_token,
                developer_token=GOOGLE_DEVELOPER_TOKEN,
                client_id=GOOGLE_CLIENT_ID,
                client_secret=GOOGLE_CLIENT_SECRET,
            )
            customer_service = client.get_service("CustomerService")
            ga_service = client.get_service("GoogleAdsService")

            accessible_customers = customer_service.list_accessible_customers()
            resource_names = accessible_customers.resource_names

            customer_data = []
            for resource_name in resource_names:
                try:
                    customer_id = resource_name.split("/")[1]

                    query = """
                        SELECT
                            customer_client.descriptive_name,
                            customer_client.id,
                            customer_client.client_customer,
                            customer_client.level,
                            customer_client.status,
                            customer_client.manager
                        FROM customer_client
                        WHERE
                            customer_client.status = 'ENABLED'
                            AND customer_client.manager = FALSE
                    """

                    stream = ga_service.search_stream(
                        customer_id=customer_id,
                        query=query,
                    )

                    for batch in stream:
                        for row in batch.results:
                            data = {}
                            data["description"] = row.customer_client.descriptive_name
                            data["customer_id"] = row.customer_client.id
                            data["manager_id"] = int(
                                (row.customer_client.resource_name).split("/")[1]
                            )
                            customer_data.append(data)

                except GoogleAdsException as ex:
                    print(
                        f'Request with ID "{ex.request_id}" failed with status '
                        f'"{ex.error.code().name}" and includes the following errors:'
                    )
                    for error in ex.failure.errors:
                        print(f'\tError with message "{error.message}".')
                        if error.location:
                            for field_path_element in error.location.field_path_elements:
                                print(f"\t\tOn field: {field_path_element.field_name}")

        except GoogleAdsException as ex:
            print(
                f'Request with ID "{ex.request_id}" failed with status '
                f'"{ex.error.code().name}" and includes the following errors:'
            )
            for error in ex.failure.errors:
                print(f'\tError with message "{error.message}".')
                if error.location:
                    for field_path_element in error.location.field_path_elements:
                        print(f"\t\tOn field: {field_path_element.field_name}")
            return Response(
                {"detail": "Failed to list clients."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(customer_data, status=status.HTTP_200_OK)


class GetCredentialsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response(
                {"detail": "Valid access token required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        gt_obj = GoogleAdsProject.objects.get(user=user)

        data = {
            "refresh_token": gt_obj.refresh_token,
            "customer_id": gt_obj.customer_id,
            "customer_name": gt_obj.customer_name,
            "manager_id": gt_obj.manager_id,
        }

        return Response(data, status=status.HTTP_200_OK)
