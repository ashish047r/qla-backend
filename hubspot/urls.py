from django.urls import path
from .views import (
    GetContactFromHubspotView,
    GetUrlView,
    GetTokenView,
    HubspotIndexView,
)
from .accounts import (
    ConnectAccountView,
    DetachAccountView,
    HubspotRefreshView,
)

urlpatterns = [
    path("get-url/", GetUrlView.as_view(), name="get-url"),
    path("get-token/", GetTokenView.as_view(), name="get-token"),
    path("connect-account/", ConnectAccountView.as_view(), name="connect-account"),
    path("detach-account/", DetachAccountView.as_view(), name="detach-account"),
    path("refresh/", HubspotRefreshView.as_view(), name="refresh"),
    path("search-contact/", GetContactFromHubspotView.as_view(), name="search-contact"),
]
