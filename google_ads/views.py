import hashlib
import os

from django.conf import settings
from google_auth_oauthlib.flow import Flow
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import GoogleAdsProject

GOOGLE_CLIENT_SECRET_PATH = settings.GOOGLE_CLIENT_SECRET_PATH


class GetUrlView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        scopes = [
            "https://www.googleapis.com/auth/adwords",
        ]

        flow = Flow.from_client_secrets_file(GOOGLE_CLIENT_SECRET_PATH, scopes=scopes)
        flow.redirect_uri = settings.REDIRECT_URI
        passthrough_val = hashlib.sha256(os.urandom(1024)).hexdigest()

        authorization_url, state = flow.authorization_url(
            access_type="offline",
            state=passthrough_val,
            prompt="consent",
            include_granted_scopes="false",
        )

        return Response(
            {
                "authorization_url": authorization_url,
                "passthrough_val": passthrough_val,
            },
            status=status.HTTP_200_OK,
        )


class GetTokenView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response(
                {"detail": "Valid access token required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        google_access_code = request.data.get("google_access_code")

        scopes = [
            "https://www.googleapis.com/auth/adwords",
        ]

        flow = Flow.from_client_secrets_file(GOOGLE_CLIENT_SECRET_PATH, scopes=scopes)
        flow.redirect_uri = settings.REDIRECT_URI
        flow.fetch_token(code=google_access_code)
        refresh_token = flow.credentials.refresh_token

        google_token = GoogleAdsProject.objects.create(
            refresh_token=refresh_token,
            user=user,
        )
        google_token.save()

        return Response(
            {
                "connected": True,
                "user": user.username,
            },
            status=status.HTTP_200_OK,
        )


class ConnectAccountView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response(
                {"detail": "Valid access token required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        customer_id = request.data.get("customer_id")
        customer_name = request.data.get("customer_name")
        manager_id = request.data.get("manager_id")

        gt_obj = GoogleAdsProject.objects.get(user=user)
        gt_obj.customer_id = customer_id
        gt_obj.customer_name = customer_name
        gt_obj.manager_id = manager_id
        gt_obj.save()

        return Response(
            {"message": "Customer ID attached successfully."},
            status=status.HTTP_200_OK,
        )


class DetachAccountView(APIView):
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
        gt_obj.delete()
        return Response(
            {"message": "Customer ID detached successfully."},
            status=status.HTTP_200_OK,
        )

