from django.urls import path
from .views import SignupView, ActivateAccountView, LoginView, ForgotPasswordView, ResetPasswordView, LogoutView, GetUserInfoView, UserProfileView, ListProfilePixel
from .integrations import IntegrationsStatusView
from rest_framework_simplejwt.views import TokenRefreshView


urlpatterns = [
    path("signup/", SignupView.as_view(), name="signup"),
    path("activate/<uid>/<token>/", ActivateAccountView.as_view(), name="activate"),
    path("login/", LoginView.as_view(), name="login"),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("reset-password/<uid>/<token>/", ResetPasswordView.as_view(), name="reset-password"),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('integrations-status/', IntegrationsStatusView.as_view(), name="integrations-status"),
    path('logout/', LogoutView.as_view(), name="logout"),
    path('get-user-info/', GetUserInfoView.as_view(), name="get-user-info"),
    path('user-profile/', UserProfileView.as_view(), name="user-profile"),
    path('list-pixel/', ListProfilePixel.as_view(), name="generate-profile-pixel"),
    
]
