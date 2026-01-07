from django.conf import settings
from django.http import JsonResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from facebook_ads.models import FacebookAdsProject
from .oauth import exchange_code_for_token
from .meta_pixel import send_conversion_events


FB_APP_ID = settings.FB_APP_ID
FB_APP_SECRET = settings.FB_APP_SECRET
FB_REDIRECT_URI = settings.REDIRECT_URI


class GetUrlView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        authorization_url = (
            "https://www.facebook.com/v17.0/dialog/oauth?"
            f"client_id={FB_APP_ID}&redirect_uri={FB_REDIRECT_URI}&scope=ads_management"
        )
        return JsonResponse({"authorization_url": authorization_url})


class GetTokenView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response(
                {"detail": "Valid access token required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        code = request.data.get("code")
        access_token = exchange_code_for_token(code)
        FacebookAdsProject.objects.create(user=user, access_token=access_token)

        return Response({"message": "Facebook connection saved successfully"})


class SendConversionEventView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        fb = FacebookAdsProject.objects.get(user=request.user)
        results = send_conversion_events(
            request.user,
            fb,
            request.data.get("conversions", [])
        )
        return Response({"results": results})
