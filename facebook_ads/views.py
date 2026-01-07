import requests
import json

from django.shortcuts import redirect, render
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework import status
from .models import FacebookAdsProject
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.permissions import IsAuthenticated

from tracker.models import Company, CompanyVisit
from django.utils import timezone
from datetime import timezone as dt_timezone
from urllib.parse import urlparse
import hashlib



def sha256_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_str(value):
    return value.strip() if isinstance(value, str) and value.strip() else None





FB_APP_ID= settings.FB_APP_ID
FB_APP_SECRET= settings.FB_APP_SECRET
FB_REDIRECT_URI= settings.REDIRECT_URI

class GetUrlView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    def get(self, request):
        fb_login_url = (
            f"https://www.facebook.com/v17.0/dialog/oauth?"
            f"client_id={FB_APP_ID}&redirect_uri={FB_REDIRECT_URI}&scope=ads_management"
        )
        return JsonResponse({"authorization_url": fb_login_url})



class GetTokenView(APIView):
    permission_classes = [IsAuthenticated]  # Require authentication
    authentication_classes = [JWTAuthentication]  # Use JWT auth

    def post(self, request):

        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)

        code = request.data.get("code")

        token_url = 'https://graph.facebook.com/v17.0/oauth/access_token'
        params = {
            'client_id': FB_APP_ID,
            'redirect_uri': FB_REDIRECT_URI,
            'client_secret': FB_APP_SECRET,
            'code': code
        }
        resp = requests.get(token_url, params=params)
        data = resp.json()

        access_token = data.get('access_token')

        FacebookAdsProject.objects.create(user=user,
                                            access_token=access_token)

        return JsonResponse({"message": "Facebook connection saved successfully"})


class ListClientsView(APIView):
    permission_classes = [IsAuthenticated]  # Require authentication
    authentication_classes = [JWTAuthentication]  # Use JWT auth

    def get(self, request):

        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)


        facebook_obj = FacebookAdsProject.objects.get(user=user)
        access_token = facebook_obj.access_token


        url = 'https://graph.facebook.com/v23.0/me/adaccounts'
        params = {'access_token': access_token, 'fields': 'id,name'}
        resp = requests.get(url, params=params)

        data = resp.json()

        simplified_data = [
                {
                    "id": account["id"],
                    "name": account["name"]
                }
                for account in data.get("data", [])
            ]


        return JsonResponse(simplified_data, safe=False)


class ConnectAccountView(APIView):
    permission_classes = [IsAuthenticated]  # Require authentication
    authentication_classes = [JWTAuthentication]  # Use JWT auth

    def post(self, request):

        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)

        customer_id = request.data.get("id")
        customer_name = request.data.get("name")


        fb_obj = FacebookAdsProject.objects.get(user=user)
        fb_obj.customer_id = customer_id
        fb_obj.customer_name = customer_name
        fb_obj.save()

        return JsonResponse({"message": "Facebook ID attached successfully."})


class DetachAccountView(APIView):
    permission_classes = [IsAuthenticated]  # Require authentication
    authentication_classes = [JWTAuthentication]  # Use JWT auth
    
    def get(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)
        fb_obj = FacebookAdsProject.objects.get(user=user)
        fb_obj.delete()
        return Response({"message": "Customer ID detached successfully."}, status=status.HTTP_200_OK)


class GetCredentialsView(APIView):
    permission_classes = [AllowAny]  # Require authentication
    authentication_classes = []  # Use JWT auth
    
    def get(self, request):

        user = request.user

        
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)

        fb_obj = FacebookAdsProject.objects.get(user=user)

        data = {
            "access_token": fb_obj.access_token,
            "customer_id": fb_obj.customer_id,
            "customer_name": fb_obj.customer_name
        }

        return Response(data, status=status.HTTP_200_OK)


class MetaPixelCredentialsView(APIView):
    permission_classes = [IsAuthenticated]  # Require authentication
    authentication_classes = [JWTAuthentication]  # Use JWT auth
    
    def get(self, request):

        user = request.user

        print("user", user)
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)

        fb_obj = FacebookAdsProject.objects.get(user=user)

        data = {
            "meta_pixel_id": fb_obj.meta_pixel_id,
            "meta_pixel_access_token": fb_obj.meta_pixel_access_token,
         }

        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):

        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)

        fb_obj = FacebookAdsProject.objects.get(user=user)

        meta_pixel_id = request.data.get("meta_pixel_id")
        meta_pixel_access_token = request.data.get("meta_pixel_access_token")

        print("meta_pixel_id", meta_pixel_id)
        print("meta_pixel_access_token", meta_pixel_access_token)


        if not meta_pixel_id or not meta_pixel_access_token:
            return Response({"detail": "Meta pixel ID and access token are required."}, status=status.HTTP_400_BAD_REQUEST)

        fb_obj.meta_pixel_id = meta_pixel_id
        fb_obj.meta_pixel_access_token = meta_pixel_access_token
        fb_obj.save()
        return Response({"message": "Meta pixel ID and access token saved successfully."}, status=status.HTTP_200_OK)




class SendConversionEventView(APIView):
    permission_classes = [IsAuthenticated]  # Require authentication
    authentication_classes = [JWTAuthentication]  # Use JWT auth

    def _format_fbc(self, click_id, domain, observed_time):
        """
        Build the fbc value using the fbclid (click_id), the domain depth, and
        the timestamp when the fbclid was first observed.
        """
        hostname = ""
        if domain:
            hostname = domain.split(":")[0]
        try:
            parsed = urlparse(domain)
            hostname = parsed.hostname or hostname
        except Exception:
            hostname = hostname or domain or ""

        parts = [p for p in (hostname or "").split(".") if p]
        subdomain_index = max(len(parts) - 1, 0)

        if timezone.is_naive(observed_time):
            observed_time = timezone.make_aware(observed_time, dt_timezone.utc)
        else:
            observed_time = observed_time.astimezone(dt_timezone.utc)
        creation_time_ms = int(observed_time.timestamp() * 1000)

        return f"fb.{subdomain_index}.{creation_time_ms}.{click_id}"


    def post(self, request):

        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Valid access token required."}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            fb_obj = FacebookAdsProject.objects.get(user=user)
        except FacebookAdsProject.DoesNotExist:
            return Response({"detail": "Facebook account not connected."}, status=status.HTTP_400_BAD_REQUEST)

        dataset_id = fb_obj.meta_pixel_id
        access_token = fb_obj.meta_pixel_access_token

        if not dataset_id or not access_token:
            return Response({"detail": "Meta pixel credentials are missing."}, status=status.HTTP_400_BAD_REQUEST)

        url = f"https://graph.facebook.com/v24.0/{dataset_id}/events"

        # Expecting a list of objects from frontend
        events_data = request.data.get("conversions")
        if not events_data or not isinstance(events_data, list):
            return Response({"detail": "A list of conversion event objects is required as 'events'."}, status=status.HTTP_400_BAD_REQUEST)

        response_list = []

        for event in events_data:
            click_id = event.get("click_id")
            if not click_id:
                response_list.append({"input": event, "error": "click_id is required for conversion event."})
                continue

            company = (
                Company.objects.filter(user=user, click_id=click_id)
                .order_by("timestamp")
                .first()
            )
            if not company:
                response_list.append({"input": event, "error": "No company found for provided click_id."})
                continue

            company_visit = (
                CompanyVisit.objects.filter(company=company)
                .order_by("timestamp")
                .first()
            )
            if not company_visit:
                response_list.append({"input": event, "error": "No company visit found for provided click_id."})
                continue

            ip_address = company.ip_address
            if not ip_address:
                response_list.append({"input": event, "error": "IP address missing on company record."})
                continue

            event_name = "GS ICP Company Visit"
            visit_ts = company_visit.timestamp
            print("visit_ts", visit_ts)
            if timezone.is_naive(visit_ts):
                visit_ts = timezone.make_aware(visit_ts, dt_timezone.utc)
            else:
                visit_ts = visit_ts.astimezone(dt_timezone.utc)
            event_time = int(visit_ts.timestamp())
            print("event_time", event_time)
            user_agent = company_visit.user_agent

            domain_for_fbc = company.domain or (urlparse(company.url_visited).hostname if company.url_visited else "")
            fbc = self._format_fbc(click_id, domain_for_fbc, company.timestamp or visit_ts)
            print("fbc", fbc)

            # --------------------------------------------------
            # GEO DATA (HASHED PER META REQUIREMENTS)
            #   - city      -> ct
            #   - state     -> st
            #   - zip code  -> zp
            # These must be SHA-256 hashed before sending.
            # --------------------------------------------------
            state_raw = normalize_str(company.state)
            city_raw = normalize_str(company.city)
            postal_code_raw = normalize_str(company.postal_code)

            st = sha256_hash((state_raw or "").lower())
            ct = sha256_hash((city_raw or "").lower())
            zp = sha256_hash((postal_code_raw or "").lower())

            # --------------------------------------------------
            # EXTERNAL ID (HASHED - SHA256)
            # --------------------------------------------------
            external_id = sha256_hash(str(user.id))

            data = [
                {
                    "event_name": event_name,
                    "event_time": event_time,
                    "user_data": {
                        "client_ip_address": ip_address,
                        "client_user_agent": user_agent,
                        "fbc": fbc,
                        "external_id": external_id,
                        "st": st,
                        "ct": ct,
                        "zp": zp,
                    },
                    "action_source": "website",
                }
            ]

            try:
                response = requests.post(
                    url,
                    files={
                        "data": (None, json.dumps(data)),
                        "access_token": (None, access_token),
                    },
                    timeout=10,
                )
                try:
                    resp_json = response.json()
                except ValueError:
                    resp_json = {"raw": response.text}
                response_list.append({"input": event, "response": resp_json, "status_code": response.status_code})
            except Exception as e:
                response_list.append({"input": event, "error": str(e)})

        print("response_list", response_list)
        return Response({"results": response_list}, status=status.HTTP_200_OK)




