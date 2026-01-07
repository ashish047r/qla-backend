import requests
from django.conf import settings
from facebook_ads.models import FacebookAdsProject


FB_APP_ID = settings.FB_APP_ID
FB_APP_SECRET = settings.FB_APP_SECRET
FB_REDIRECT_URI = settings.REDIRECT_URI


def build_facebook_login_url():
    return (
        f"https://www.facebook.com/v17.0/dialog/oauth?"
        f"client_id={FB_APP_ID}&redirect_uri={FB_REDIRECT_URI}&scope=ads_management"
    )


def exchange_code_for_token(code):
    token_url = "https://graph.facebook.com/v17.0/oauth/access_token"
    params = {
        "client_id": FB_APP_ID,
        "redirect_uri": FB_REDIRECT_URI,
        "client_secret": FB_APP_SECRET,
        "code": code,
    }
    response = requests.get(token_url, params=params)
    response.raise_for_status()
    return response.json().get("access_token")


def save_access_token(user, access_token):
    return FacebookAdsProject.objects.create(
        user=user,
        access_token=access_token
    )


def list_ad_accounts(access_token):
    url = "https://graph.facebook.com/v23.0/me/adaccounts"
    params = {"access_token": access_token, "fields": "id,name"}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json().get("data", [])

