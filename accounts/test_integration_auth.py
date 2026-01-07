from rest_framework.test import APITestCase
from django.contrib.auth.models import User
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from unittest.mock import patch
import uuid


class SignupIntegrationTest(APITestCase):

    @patch("accounts.views.send_mail")
    def test_signup_full_flow(self, mock_send_mail):
        email = f"user_{uuid.uuid4().hex}@test.com"
        password = "pepperoni12"

        # ---- SIGNUP ----
        signup_response = self.client.post(
            "/api/accounts/signup/",
            {"username": email, "password": password},
            format="json"
        )

        self.assertEqual(signup_response.status_code, 201)

        user = User.objects.get(username=email)
        self.assertFalse(user.is_active)

        # ---- user profile created by signal ----
        self.assertTrue(hasattr(user, "userprofile"))

        # ---- LOGIN SHOULD FAIL (inactive user) ----
        login_response = self.client.post(
            "/api/accounts/login/",
            {"username": email, "password": password},
            format="json"
        )

        self.assertEqual(login_response.status_code, 401)

        # ---- ACTIVATE ACCOUNT ----
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        activate_response = self.client.get(
            f"/api/accounts/activate/{uid}/{token}/"
        )

        self.assertEqual(activate_response.status_code, 200)

        user.refresh_from_db()
        self.assertTrue(user.is_active)

        # ---- LOGIN SUCCESS ----
        login_response = self.client.post(
            "/api/accounts/login/",
            {"username": email, "password": password},
            format="json"
        )

        self.assertEqual(login_response.status_code, 200)
        self.assertIn("access", login_response.data)
        self.assertIn("refresh", login_response.data)







class LoginIntegrationTest(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="login@test.com",
            password="pepperoni12",
            is_active=True
        )

    def test_login_and_access_protected_endpoint(self):
        # ---- LOGIN ----
        response = self.client.post(
            "/api/accounts/login/",
            {
                "username": "login@test.com",
                "password": "pepperoni12"
            },
            format="json"
        )

        access = response.data["access"]

        # ---- USE TOKEN ----
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access}"
        )

        protected_response = self.client.get(
            "/api/accounts/get-user-info/"
        )

        self.assertEqual(protected_response.status_code, 200)
        self.assertEqual(
            protected_response.data["user"]["username"],
            "login@test.com"
        )



class ForgotResetPasswordIntegrationTest(APITestCase):

    @patch("accounts.views.send_mail")
    def test_forgot_and_reset_password_flow(self, mock_send_mail):
        user = User.objects.create_user(
            username="reset@test.com",
            password="oldpass123",
            is_active=True
        )

        # ---- FORGOT PASSWORD ----
        forgot_response = self.client.post(
            "/api/accounts/forgot-password/",
            {"username": user.username},
            format="json"
        )

        self.assertEqual(forgot_response.status_code, 200)

        # ---- GENERATE RESET TOKEN ----
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        # ---- RESET PASSWORD ----
        reset_response = self.client.post(
            f"/api/accounts/reset-password/{uid}/{token}/",
            {"password": "newpass456"},
            format="json"
        )

        self.assertEqual(reset_response.status_code, 200)

        # ---- LOGIN WITH NEW PASSWORD ----
        login_response = self.client.post(
            "/api/accounts/login/",
            {
                "username": user.username,
                "password": "newpass456"
            },
            format="json"
        )

        self.assertEqual(login_response.status_code, 200)
        self.assertIn("access", login_response.data)





from google_ads.models import GoogleAdsProject
from facebook_ads.models import FacebookAdsProject


class IntegrationStatusIntegrationTest(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="integration@test.com",
            password="pepperoni12",
            is_active=True
        )

        # ---- LOGIN ----
        response = self.client.post(
            "/api/accounts/login/",
            {
                "username": self.user.username,
                "password": "pepperoni12"
            },
            format="json"
        )

        self.access = response.data["access"]


    def test_integration_status_flow(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.access}"
        )

        # ---- CREATE INTEGRATIONS ----
        GoogleAdsProject.objects.create(
            user=self.user,
            customer_name="Google Ads"
        )

        FacebookAdsProject.objects.create(
            user=self.user,
            customer_name="Facebook Ads"
        )

        response = self.client.get(
            "/api/accounts/integrations-status/"
        )

        self.assertEqual(response.status_code, 200)

        # Parse JSON response since view returns JsonResponse, not DRF Response
        response_data = response.json()

        self.assertEqual(
            response_data["google_ads"]["status"],
            "connected"
        )
        self.assertEqual(
            response_data["facebook"]["status"],
            "connected"
        )
        self.assertEqual(
            response_data["hubspot"]["status"],
            "not connected"
        )
