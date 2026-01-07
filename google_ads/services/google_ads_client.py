from google.ads.googleads.client import GoogleAdsClient


def build_client(refresh_token, *, developer_token, client_id, client_secret):
    """
    Build a GoogleAdsClient from runtime credentials. Keeps client creation
    centralized so views stay thin.
    """
    credentials = {
        "developer_token": developer_token,
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "use_proto_plus": True,
    }
    return GoogleAdsClient.load_from_dict(credentials)
from google.ads.googleads.client import GoogleAdsClient


def build_client(
    refresh_token: str,
    *,
    developer_token: str,
    client_id: str,
    client_secret: str,
    use_proto_plus: bool = True,
) -> GoogleAdsClient:
    """Create a GoogleAdsClient using provided credentials."""
    credentials = {
        "developer_token": developer_token,
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "use_proto_plus": use_proto_plus,
    }
    return GoogleAdsClient.load_from_dict(credentials)

