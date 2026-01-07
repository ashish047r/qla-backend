import logging
import sys

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import HubspotProject
from .views import refresh_access_token

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Ensure logs from this module reach the console even if Django logging isn't configured for INFO.
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False


class ConnectAccountView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)

        account_id = request.data.get("hubspot_account_id")
        account_name = request.data.get("hubspot_account_name")
        user_name = request.data.get("hubspot_user_name")

        if not account_id:
            return Response({"error": "hubspot_account_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        token_obj = HubspotProject.objects.filter(user=user).order_by("-updated_at").first()
        if not token_obj:
            return Response({"error": "HubSpot account not connected."}, status=status.HTTP_400_BAD_REQUEST)

        token_obj.hubspot_account_id = account_id
        token_obj.hubspot_account_name = account_name
        token_obj.hubspot_user_name = user_name or token_obj.hubspot_user_name
        token_obj.save(update_fields=["hubspot_account_id", "hubspot_account_name", "hubspot_user_name", "updated_at"])

        return Response({"message": "HubSpot account details updated successfully."}, status=status.HTTP_200_OK)


class DetachAccountView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)

        token_obj = HubspotProject.objects.filter(user=user).first()
        if not token_obj:
            return Response({"error": "HubSpot account not connected."}, status=status.HTTP_400_BAD_REQUEST)

        token_obj.delete()
        return Response({"message": "HubSpot account detached successfully."}, status=status.HTTP_200_OK)


class HubspotRefreshView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)

        refresh_token = request.data.get("refresh_token")

        try:
            token_obj = HubspotProject.objects.filter(user=user).order_by("-updated_at").first()
            if not token_obj and refresh_token:
                token_obj = HubspotProject(
                    user=user,
                    refresh_token=refresh_token,
                    access_token="",
                )

            if not token_obj:
                return Response({"error": "HubSpot account not connected."}, status=status.HTTP_400_BAD_REQUEST)

            token_obj, tokens = refresh_access_token(token_obj)

            return Response({
                "access_token": token_obj.access_token,
                "expires_in": tokens.get("expires_in", 1800),
                "refresh_token": token_obj.refresh_token,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("HubSpot refresh failed: %s", e)
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

