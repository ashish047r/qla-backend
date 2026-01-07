# hubspot/views.py
import logging
import sys
import urllib.parse
from datetime import datetime, timezone as dt_timezone

import requests
from django.conf import settings
from django.core import signing
from django.contrib.auth import get_user_model
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from .search import (
    search_contact_by_gclid,
    get_contact,
    get_contact_company,
    get_company_deals,
    get_contact_meetings,
    get_account_currency,
    format_response,
)

from .models import HubspotProject

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Ensure logs from this module reach the console even if Django logging isn't configured for INFO.
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False


HUBSPOT_CLIENT_ID = settings.HUBSPOT_CLIENT_ID
HUBSPOT_CLIENT_SECRET = settings.HUBSPOT_CLIENT_SECRET
HUBSPOT_REDIRECT_URI = getattr(settings, "HUBSPOT_REDIRECT_URI", settings.REDIRECT_URI)
HUBSPOT_GCLID_PROPERTY = "hs_google_click_id"
HUBSPOT_FBCLID_PROPERTY = "hs_facebook_click_id"

def parse_scopes(scope_value):
    """Return space-delimited scopes with quoting or separators removed."""
    if not scope_value:
        return ""

    cleaned = scope_value.strip().strip('"').strip("'")
    cleaned = cleaned.replace(",", " ")
    scopes = [scope for scope in cleaned.split() if scope]
    return " ".join(scopes)


# Only the scopes needed
HUBSPOT_SCOPES = parse_scopes(getattr(settings, "HUBSPOT_OAUTH_SCOPES", ""))

AUTH_URL = "https://app.hubspot.com/oauth/authorize"
TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"
ME_URL = "https://api.hubapi.com/integrations/v1/me"
TOKEN_INFO_URL = "https://api.hubapi.com/oauth/v1/access-tokens/{token}"
ACCOUNT_INFO_URL = "https://api.hubapi.com/account-info/v3/details"
USER_INFO_URL = "https://api.hubapi.com/settings/v3/users/{user_id}"
STATE_SIGNER = signing.TimestampSigner(salt="hubspot_state")
STATE_MAX_AGE_SECONDS = 3600  # accept callback within 1 hour

FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}


def hubspot_post(url, data):
    r = requests.post(url, data=data, headers=FORM_HEADERS, timeout=10)
    if r.status_code != 200:
        raise ValueError(r.json())
    return r.json()


def hubspot_get(url, token):
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    if r.status_code != 200:
        raise ValueError(r.json())
    return r.json()


def hubspot_token_info(access_token):
    url = TOKEN_INFO_URL.format(token=access_token)
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        raise ValueError(r.json())
    return r.json()


def hubspot_account_info(token):
    r = requests.get(ACCOUNT_INFO_URL, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    if r.status_code != 200:
        raise ValueError(r.json())
    return r.json()


def hubspot_user_info(user_id, token):
    url = USER_INFO_URL.format(user_id=user_id)
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    if r.status_code != 200:
        raise ValueError(r.json())
    return r.json()


def refresh_access_token(token_obj):
    """Refresh and persist the HubSpot access token for a stored record."""
    refresh_token = token_obj.refresh_token
    if not refresh_token:
        raise ValueError("No refresh token saved for this HubSpot account.")

    tokens = hubspot_post(TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": HUBSPOT_CLIENT_ID,
        "client_secret": HUBSPOT_CLIENT_SECRET,
        "refresh_token": refresh_token,
    })

    token_obj.access_token = tokens["access_token"]
    token_obj.refresh_token = tokens.get("refresh_token", refresh_token)

    save_kwargs = {}
    if token_obj.pk:
        save_kwargs["update_fields"] = ["access_token", "refresh_token", "updated_at"]
    token_obj.save(**save_kwargs)
    return token_obj, tokens


def get_valid_access_token(user):
    """Return a non-expired HubSpot access token for the user, refreshing if necessary."""
    token_obj = HubspotProject.objects.filter(user=user).order_by("-updated_at").first()
    if not token_obj:
        raise HubspotProject.DoesNotExist("No HubSpot tokens stored for this user. Connect HubSpot first.")

    def _refresh_and_return():
        refreshed_obj, _ = refresh_access_token(token_obj)
        return refreshed_obj.access_token

    try:
        info = hubspot_token_info(token_obj.access_token)
        expires_in = info.get("expires_in")
        if expires_in is not None and expires_in <= 60:
            logger.info("HubSpot access token expiring soon (%s s); refreshing.", expires_in)
            return _refresh_and_return()
    except ValueError as exc:
        logger.warning("HubSpot access token invalid/expired, refreshing: %s", exc)
        return _refresh_and_return()
    except Exception as exc:
        logger.exception("Failed to validate HubSpot token; attempting refresh: %s", exc)
        return _refresh_and_return()

    return token_obj.access_token


def build_install_url(state=None):
    params = {
        "client_id": HUBSPOT_CLIENT_ID,
        "redirect_uri": HUBSPOT_REDIRECT_URI,
        "scope": HUBSPOT_SCOPES,
        "response_type": "code",
    }
    if state:
        params["state"] = state

    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def resolve_user_from_state(state_value):
    """Return the user referenced by a signed state token."""
    if not state_value:
        return None
    try:
        unsigned = STATE_SIGNER.unsign(state_value, max_age=STATE_MAX_AGE_SECONDS)
        user_id = int(unsigned)
        User = get_user_model()
        return User.objects.filter(id=user_id).first()
    except Exception:
        return None


def exchange_code_for_tokens(code, user):
    """Exchange an OAuth code for HubSpot tokens and persist them."""
    tokens = hubspot_post(TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": HUBSPOT_CLIENT_ID,
        "client_secret": HUBSPOT_CLIENT_SECRET,
        "redirect_uri": HUBSPOT_REDIRECT_URI,
        "code": code,
    })

    logger.info("HubSpot token exchange response: %s", tokens)

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise ValueError("HubSpot did not return a refresh token.")

    me = {}
    token_info = {}
    account_info = {}
    user_details = {}

    try:
        me = hubspot_get(ME_URL, access_token)
        logger.info("HubSpot /me response: %s", me)
    except Exception:
        me = {}

    try:
        token_info = hubspot_token_info(access_token)
        logger.info("HubSpot access-token info response: %s", token_info)
    except Exception:
        token_info = {}

    try:
        account_info = hubspot_account_info(access_token)
        logger.info("HubSpot account-info response: %s", account_info)
    except Exception:
        account_info = {}

    user_id = tokens.get("user_id") or token_info.get("user_id")
    if user_id:
        try:
            user_details = hubspot_user_info(user_id, access_token)
            logger.info("HubSpot settings user response: %s", user_details)
        except Exception:
            user_details = {}

    hub_id = (
        me.get("portalId")
        or tokens.get("hub_id")
        or token_info.get("hub_id")
        or token_info.get("portal_id")
        or account_info.get("portalId")
    )
    account_name = (
        account_info.get("name")
        or me.get("portalName")
        or token_info.get("hub_domain")
        or tokens.get("hub_domain")
        or tokens.get("hub_name")
    )

    user_info = me.get("user") or tokens.get("user") or {}
    user_name = (
        user_details.get("displayName")
        or " ".join(filter(None, [user_details.get("firstName"), user_details.get("lastName")])).strip()
        or user_details.get("email")
        or user_info.get("fullName")
        or user_info.get("email")
        or tokens.get("user_email")
        or "Unknown User"
    )

    if user_name == "Unknown User":
        user_name = (
            token_info.get("user")
            or token_info.get("user_email")
            or token_info.get("userEmail")
            or user_name
        )

    HubspotProject.objects.update_or_create(
        user=user,
        defaults={
            "hubspot_account_id": str(hub_id) if hub_id else "",
            "hubspot_account_name": account_name,
            "hubspot_user_name": user_name,
            "access_token": access_token,
            "refresh_token": refresh_token,
        },
    )

    return {
        "message": "HubSpot Connected",
        "hub_id": hub_id,
        "account_name": account_name,
        "user_name": user_name,
    }


class GetUrlView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user
        state_token = STATE_SIGNER.sign(str(user.id))
        return Response({"authorization_url": build_install_url(state_token), "state": state_token})


class GetTokenView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        user = request.user if request.user and request.user.is_authenticated else None
        state = request.data.get("state")
        resolved_user = resolve_user_from_state(state) if state else None
        if resolved_user:
            if user and resolved_user.id != user.id:
                return Response({"detail": "State token does not match authenticated user."},
                                status=status.HTTP_400_BAD_REQUEST)
            user = resolved_user

        if not user:
            return Response({"detail": "Valid access token or state required."},
                            status=status.HTTP_401_UNAUTHORIZED)

        code = request.data.get("code") or request.data.get("auth_token")
        if not code:
            return Response({"error": "Missing code"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payload = exchange_code_for_tokens(code, user)
            return Response(payload, status=status.HTTP_200_OK)
        except ValueError as exc:
            logger.warning("HubSpot token exchange validation failed: %s", exc)
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception("HubSpot OAuth exchange failed: %s", exc)
            return Response({"error": "OAuth failed", "details": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class GetContactFromHubspotView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        identifier_type = (request.data.get("identifier") or "").lower()
        conversions = request.data.get("conversions")

        logger.info(
            "HubSpot contact lookup requested: identifier=%s, count=%s, user_id=%s",
            identifier_type,
            len(conversions) if isinstance(conversions, list) else None,
            getattr(request.user, "id", None),
        )

        if identifier_type not in ("gclid", "fbclid"):
            return Response({"error": "identifier must be 'gclid' or 'fbclid'"}, status=400)

        if not isinstance(conversions, list) or not conversions:
            return Response({"error": "conversions must be a non-empty list"}, status=400)

        property_name = HUBSPOT_GCLID_PROPERTY if identifier_type == "gclid" else HUBSPOT_FBCLID_PROPERTY
        fallback_data = {
            "email": "null",
            "meeting_booked_number": None,
            "deal_amount_number": None,
            "deal_amount": None,
            "lifecyclestage": "null",
            "companyname": None,
            "currency": "null",
            "currency_symbol": "null",
        }

        try:
            access_token = get_valid_access_token(request.user)
        except HubspotProject.DoesNotExist as exc:
            return Response({"error": str(exc)}, status=503)
        except Exception:
            return Response({"error": "Unable to obtain HubSpot access token"}, status=500)

        results = []
        for item in conversions:
            conversion_id = item.get("conversion_id") if isinstance(item, dict) else None
            if not conversion_id:
                logger.warning("HubSpot lookup: missing conversion_id in item=%s", item)
                results.append({"conversion_id": conversion_id, "error": "conversion_id is required"})
                continue

            provided_date = None
            if isinstance(item, dict):
                provided_date = item.get("timestamp") or item.get("date") or item.get("conversion_time")

            min_date = None
            if provided_date:
                min_date = parse_filter_date(provided_date)
                if min_date:
                    logger.info("HubSpot lookup: using provided date %s for %s", min_date, conversion_id)
                else:
                    logger.warning("HubSpot lookup: invalid date format '%s' for %s", provided_date, conversion_id)
            else:
                logger.info("HubSpot lookup: no date provided for %s; using no min_date filter", conversion_id)

            contact_search = search_contact_by_gclid(conversion_id, access_token, property_name)
            if not contact_search:
                logger.info("HubSpot lookup: no contact match for %s using %s", conversion_id, property_name)
                results.append({"conversion_id": conversion_id, "data": fallback_data})
                continue

            contact_id = contact_search["id"]
            logger.debug("HubSpot lookup: found contact_id=%s for %s", contact_id, conversion_id)
            contact = get_contact(contact_id, access_token)
            company = get_contact_company(contact_id, access_token)
            company_id = company["id"] if company else None
            meetings = get_contact_meetings(contact_id, access_token, min_date=min_date)
            deals = get_company_deals(company_id, access_token, min_date=min_date) if company_id else []
            currency = get_account_currency(access_token)

            final_output = format_response(contact, company, deals, meetings, currency)
            logger.debug("HubSpot lookup: assembled response for %s => %s", conversion_id, final_output)
            results.append({"conversion_id": conversion_id, "data": final_output})

        return Response({"results": results}, status=status.HTTP_200_OK)


class HubspotIndexView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            "endpoints": {
                "get-url": "get-url/",
                "callback": "callback/",
                "refresh": "refresh/",
                "search-contact": "search-contact/",
            }
        })


def parse_filter_date(value):
    """Parse YYYY-MM-DD or ISO date/time strings into an aware datetime."""
    if not value:
        return None

    try:
        normalized = value.replace("Z", "+00:00") if isinstance(value, str) else value
        dt_obj = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            dt_obj = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None

    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=dt_timezone.utc)

    # Normalize to seconds precision to avoid HubSpot filtering mismatches
    return dt_obj.replace(microsecond=0)
