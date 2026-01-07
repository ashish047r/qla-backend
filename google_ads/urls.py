from django.urls import path

from .accounts import GetCredentialsView, ListClientsView
from .views import ConnectAccountView, DetachAccountView, GetTokenView, GetUrlView

urlpatterns = [
    path("get-url/", GetUrlView.as_view(), name="get-url"),
    path("get-token/", GetTokenView.as_view(), name="get-token"),
    path("connect-account/", ConnectAccountView.as_view(), name="connect-account"),
    path("detach-account/", DetachAccountView.as_view(), name="detach-account"),
    path("list-clients/", ListClientsView.as_view(), name="list-clients"),
    path("get-credentials/", GetCredentialsView.as_view(), name="get-credentials"),
]
