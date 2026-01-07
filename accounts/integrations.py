from facebook_ads.models import FacebookAdsProject
from google_ads.models import GoogleAdsProject
from hubspot.models import HubspotProject

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.permissions import IsAuthenticated

from django.http import JsonResponse


class IntegrationsStatusView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    def get(self, request):

        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)


        data = {}
        gt_obj = GoogleAdsProject.objects.filter(user=user).last()
        if gt_obj and gt_obj.customer_name:
            data["google_ads"] = {
                "status": "connected",
                "name": gt_obj.customer_name
            }
        else:
            data["google_ads"] = {
                "status": "not connected",
                "name": ""
            }

        fb_obj = FacebookAdsProject.objects.filter(user=user).last()
        if fb_obj and fb_obj.customer_name:
            data["facebook"] = {
                "status": "connected",
                "name": fb_obj.customer_name
            }
        else:
            data["facebook"] = {
                "status": "not connected",
                "name": ""
            }

        hs_obj = HubspotProject.objects.filter(user=user).last()
        if hs_obj and hs_obj.hubspot_account_name:
            data["hubspot"] = {
                "status": "connected",
                "name": hs_obj.hubspot_account_name
            }
        else:
            data["hubspot"] = {
                "status": "not connected",
                "name": ""
            }


        return JsonResponse(data, safe=False)
