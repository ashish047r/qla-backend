import hashlib
import os

from google_auth_oauthlib.flow import Flow
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.permissions import IsAuthenticated
from .models import GoogleAdsProject

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException


GOOGLE_CLIENT_SECRET_PATH= settings.GOOGLE_CLIENT_SECRET_PATH
GOOGLE_CLIENT_ID = settings.GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET = settings.GOOGLE_CLIENT_SECRET
GOOGLE_DEVELOPER_TOKEN = settings.GOOGLE_DEVELOPER_TOKEN



# ------------------ SIGNUP ------------------
class GetUrlView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    def get(self, request):
        client_secrets_path = GOOGLE_CLIENT_SECRET_PATH

        scopes = [
            'https://www.googleapis.com/auth/adwords',
        ]

        flow = Flow.from_client_secrets_file(client_secrets_path, scopes=scopes) 
        flow.redirect_uri = settings.REDIRECT_URI
        passthrough_val = hashlib.sha256(os.urandom(1024)).hexdigest()

        authorization_url, state = flow.authorization_url(
            access_type='offline',
            state=passthrough_val,
            prompt='consent',
            include_granted_scopes='false',
        )

        return Response({"authorization_url": authorization_url, "passthrough_val": passthrough_val}, status=status.HTTP_200_OK)


# ------------------ GET TOKEN ------------------


class GetTokenView(APIView):
    permission_classes = [IsAuthenticated]  # Require authentication
    authentication_classes = [JWTAuthentication]  # Use JWT auth

    def post(self, request):
        # The user is extracted by JWTAuthentication and available as request.user
        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)

        google_access_code = request.data.get("google_access_code")

        client_secrets_path = GOOGLE_CLIENT_SECRET_PATH
        scopes = [
            'https://www.googleapis.com/auth/adwords',
        ]

        flow = Flow.from_client_secrets_file(client_secrets_path, scopes=scopes)
        flow.redirect_uri = settings.REDIRECT_URI
        flow.fetch_token(code=google_access_code)
        refresh_token = flow.credentials.refresh_token


        google_token = GoogleAdsProject.objects.create(
                refresh_token=refresh_token,
                user=user
            )
        google_token.save()

        # Optionally respond with the authenticated user info
        return Response({
            "connected": True,
            "user": user.username,
        }, status=status.HTTP_200_OK)


class ConnectAccountView(APIView):
    permission_classes = [IsAuthenticated]  # Require authentication
    authentication_classes = [JWTAuthentication]  # Use JWT auth

    def post(self, request):

        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)

        customer_id = request.data.get("customer_id")
        customer_name = request.data.get("customer_name")
        manager_id = request.data.get("manager_id")
        
        
        gt_obj = GoogleAdsProject.objects.get(user=user)
        gt_obj.customer_id = customer_id
        gt_obj.customer_name = customer_name
        gt_obj.manager_id = manager_id
        gt_obj.save()  

        return Response({"message": "Customer ID attached successfully."}, status=status.HTTP_200_OK)



class DetachAccountView(APIView):
    permission_classes = [IsAuthenticated]  # Require authentication
    authentication_classes = [JWTAuthentication]  # Use JWT auth
    
    def get(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)
        gt_obj = GoogleAdsProject.objects.get(user=user)
        gt_obj.delete()
        return Response({"message": "Customer ID detached successfully."}, status=status.HTTP_200_OK)


class ListClientsView(APIView):
    permission_classes = [IsAuthenticated]  # Require authentication
    authentication_classes = [JWTAuthentication]  # Use JWT auth

    def get(self, request):


        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)

        gt_obj = GoogleAdsProject.objects.get(user=user)
        refresh_token = gt_obj.refresh_token

        # Configure using dict (the refresh token will be a dynamic value)
        credentials = {
            "developer_token": GOOGLE_DEVELOPER_TOKEN,
            "refresh_token": refresh_token,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "use_proto_plus": True
        }

        try:
            client = GoogleAdsClient.load_from_dict(credentials)
            customer_service = client.get_service("CustomerService")
            ga_service = client.get_service("GoogleAdsService")

            accessible_customers = customer_service.list_accessible_customers()
            resource_names = accessible_customers.resource_names

            customer_data = []
            for resource_name in resource_names:
                try:
                    customer_id = resource_name.split('/')[1]

                    # **Updated GAQL Query**
                    query = ('''
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
                    ''')

                    stream = ga_service.search_stream(
                        customer_id=customer_id,
                        query=query
                    )

                    for batch in stream:
                        for row in batch.results:
                            data = {}
                            data["description"] = row.customer_client.descriptive_name
                            data["customer_id"] = row.customer_client.id
                            data["manager_id"] =  int((row.customer_client.resource_name).split('/')[1])              
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
            sys.exit(1)


        return Response(customer_data, status=status.HTTP_200_OK)


class GetCredentialsView(APIView):
    permission_classes = [AllowAny]  # Require authentication
    authentication_classes = []  # Use JWT auth
    
    def get(self, request):


        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)


        gt_obj = GoogleAdsProject.objects.get(user=user)

        data = {
            "refresh_token": gt_obj.refresh_token,
            "customer_id": gt_obj.customer_id,
            "customer_name": gt_obj.customer_name,
            "manager_id": gt_obj.manager_id
        }

        return Response(data, status=status.HTTP_200_OK)
