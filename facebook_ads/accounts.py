import requests
from django.http import JsonResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from facebook_ads.models import FacebookAdsProject


class ListClientsView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response(
                {"detail": "Valid access token required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        fb = FacebookAdsProject.objects.get(user=user)

        url = "https://graph.facebook.com/v23.0/me/adaccounts"
        params = {"access_token": fb.access_token, "fields": "id,name"}
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        accounts = resp.json().get("data", [])

        return JsonResponse(accounts, safe=False)


class ConnectAccountView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        fb = FacebookAdsProject.objects.get(user=request.user)
        fb.customer_id = request.data.get("id")
        fb.customer_name = request.data.get("name")
        fb.save()
        return Response({"message": "Facebook ID attached successfully."})


class DetachAccountView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response(
                {"detail": "Valid access token required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        fb = FacebookAdsProject.objects.get(user=user)
        fb.delete()

        return Response(
            {"message": "Customer ID detached successfully."},
            status=status.HTTP_200_OK,
        )


class GetCredentialsView(APIView):
    """
    Return the stored Facebook Ads credentials for the authenticated user.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response(
                {"detail": "Valid access token required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        fb = FacebookAdsProject.objects.get(user=user)

        data = {
            "access_token": fb.access_token,
            "customer_id": fb.customer_id,
            "customer_name": fb.customer_name,
        }

        return Response(data, status=status.HTTP_200_OK)


class MetaPixelCredentialsView(APIView):
    """
    Get or update Meta Pixel dataset / access token for the authenticated user.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response(
                {"detail": "Valid access token required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        fb = FacebookAdsProject.objects.get(user=user)

        data = {
            "meta_pixel_id": fb.meta_pixel_id,
            "meta_pixel_access_token": fb.meta_pixel_access_token,
        }

        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response(
                {"detail": "Valid access token required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        fb = FacebookAdsProject.objects.get(user=user)
        fb.meta_pixel_id = request.data.get("meta_pixel_id", fb.meta_pixel_id)
        fb.meta_pixel_access_token = request.data.get(
            "meta_pixel_access_token", fb.meta_pixel_access_token
        )
        fb.save()

        return Response(
            {"message": "Meta Pixel credentials updated successfully."},
            status=status.HTTP_200_OK,
        )

