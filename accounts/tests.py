from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from unittest.mock import patch
import uuid  #Generates a guaranteed-unique email so tests never collide.
from rest_framework import status
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from unittest.mock import patch
from rest_framework_simplejwt.tokens import RefreshToken



class SignupTest(TestCase):

    def setUp(self):
        self.client = APIClient()

    # =====================================================
    # TEST CASE 1: New user signup succeeds
    # =====================================================
    @patch("accounts.views.send_mail")
    def test_signup_creates_user_and_returns_correct_response(self, mock_send_mail):
        fake_email = f"user_{uuid.uuid4().hex}@test.com"
        password = "pepperoni12"

        payload = {
            "username": fake_email,
            "password": password
        }

        response = self.client.post(
            "/api/accounts/signup/",
            payload,
            format="json"
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data,
            {"message": "Check your email to activate account"}
        )

        user = User.objects.get(username=fake_email)
        self.assertEqual(user.username, fake_email)
        self.assertTrue(user.check_password(password))
        self.assertFalse(user.is_active)

        mock_send_mail.assert_called_once()

    # =====================================================
    # TEST CASE 2: Duplicate signup fails
    # =====================================================
    def test_signup_fails_if_user_already_exists(self):
        existing_email = "existing_user@test.com"

        User.objects.create_user(
            username=existing_email,
            password="somepassword"
        )

        payload = {
            "username": existing_email,
            "password": "pepperoni12"
        }

        response = self.client.post(
            "/api/accounts/signup/",
            payload,
            format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"error": "Username already exists"}
        )

        self.assertEqual(
            User.objects.filter(username=existing_email).count(),
            1
        )





class LoginTest(TestCase):

    def setUp(self):
        self.client = APIClient()

        # ---- create ACTIVE user (login only works for active users) ----
        self.email = "login_user@test.com"
        self.password = "pepperoni12"

        self.user = User.objects.create_user(
            username=self.email,
            password=self.password,
            is_active=True
        )

    # =====================================================
    # TEST CASE 1: Login succeeds with correct credentials
    # =====================================================
    def test_login_success_returns_tokens(self):
        payload = {
            "username": self.email,
            "password": self.password
        }

        response = self.client.post(
            "/api/accounts/login/",
            payload,
            format="json"
        )

        # ---- status ----
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # ---- response format ----
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

        # ---- tokens should not be empty ----
        self.assertTrue(response.data["access"])
        self.assertTrue(response.data["refresh"])

    # =====================================================
    # TEST CASE 2: Login fails with wrong password
    # =====================================================
    def test_login_fails_with_invalid_password(self):
        payload = {
            "username": self.email,
            "password": "wrongpassword"
        }

        response = self.client.post(
            "/api/accounts/login/",
            payload,
            format="json"
        )

        # ---- invalid credentials ----
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # ---- token fields must not exist ----
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)






class ResetPasswordTest(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.email = "reset_user@test.com"
        self.old_password = "oldpassword123"
        self.new_password = "newpassword456"

        self.user = User.objects.create_user(
            username=self.email,
            password=self.old_password,
            is_active=True
        )

        # ---- generate UID and token EXACTLY like your app ----
        self.uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.token = default_token_generator.make_token(self.user)

        self.reset_url = f"/api/accounts/reset-password/{self.uid}/{self.token}/"

    # =====================================================
    # TEST CASE 1: Reset password succeeds
    # =====================================================
    def test_reset_password_success(self):
        payload = {
            "password": self.new_password
        }

        response = self.client.post(
            self.reset_url,
            payload,
            format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"message": "Password reset successful"}
        )

        # ---- password actually changed ----
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))

    # =====================================================
    # TEST CASE 2: Reset password fails with invalid token
    # =====================================================
    def test_reset_password_fails_with_invalid_token(self):
        invalid_token = "invalid-token"

        url = f"/api/accounts/reset-password/{self.uid}/{invalid_token}/"

        response = self.client.post(
            url,
            {"password": self.new_password},
            format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"error": "Invalid token"}
        )

    # =====================================================
    # TEST CASE 3: Reset password fails if password missing
    # =====================================================
    def test_reset_password_fails_if_password_missing(self):
        response = self.client.post(
            self.reset_url,
            {},
            format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"error": "Password is required"}
        )



class ForgotPasswordTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.email = "forgot_user@test.com"

        self.user = User.objects.create_user(
            username=self.email,
            password="somepassword",
            is_active=True
        )

    # =====================================================
    # TEST CASE 1: Forgot password succeeds
    # =====================================================
    @patch("accounts.views.send_mail")
    def test_forgot_password_sends_reset_link(self, mock_send_mail):
        payload = {
            "username": self.email
        }

        response = self.client.post(
            "/api/accounts/forgot-password/",
            payload,
            format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"message": "Password reset link sent"}
        )

        # ---- email was sent ----
        mock_send_mail.assert_called_once()

    # =====================================================
    # TEST CASE 2: Forgot password fails if email missing
    # =====================================================
    def test_forgot_password_fails_if_email_missing(self):
        response = self.client.post(
            "/api/accounts/forgot-password/",
            {},
            format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"error": "Email is required"}
        )

    # =====================================================
    # TEST CASE 3: Forgot password fails if user not found
    # =====================================================
    def test_forgot_password_fails_if_user_not_found(self):
        payload = {
            "username": "nonexistent@test.com"
        }

        response = self.client.post(
            "/api/accounts/forgot-password/",
            payload,
            format="json"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.data,
            {"error": "User not found"}
        )


#____________________________________________

                                                                                       


#________________________________________________________

from google_ads.models import GoogleAdsProject
from facebook_ads.models import FacebookAdsProject
from hubspot.models import HubspotProject


class IntegrationsStatusTest(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username="integration_user@test.com",
            password="pepperoni12",
            is_active=True
        )

        self.client.force_authenticate(user=self.user)

    # =====================================================
    # TEST CASE 1: No integrations connected
    # =====================================================
    def test_integrations_status_none_connected(self):
        response = self.client.get(
            "/api/accounts/integrations-status/"
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.json(),
            {
                "google_ads": {"status": "not connected", "name": ""},
                "facebook": {"status": "not connected", "name": ""},
                "hubspot": {"status": "not connected", "name": ""},
            }
        )

    # =====================================================
    # TEST CASE 2: Google + Facebook connected
    # =====================================================
    def test_integrations_status_some_connected(self):
        GoogleAdsProject.objects.create(
            user=self.user,
            customer_name="Google Ads Account"
        )

        FacebookAdsProject.objects.create(
            user=self.user,
            customer_name="Facebook Ad Account"
        )

        response = self.client.get(
            "/api/accounts/integrations-status/"
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.json(),
            {
                "google_ads": {
                    "status": "connected",
                    "name": "Google Ads Account"
                },
                "facebook": {
                    "status": "connected",
                    "name": "Facebook Ad Account"
                },
                "hubspot": {
                    "status": "not connected",
                    "name": ""
                },
            }
        )

    # =====================================================
    # TEST CASE 3: Unauthorized access blocked
    # =====================================================
    def test_integrations_status_requires_authentication(self):
        unauthenticated_client = APIClient()

        response = unauthenticated_client.get(
            "/api/accounts/integrations-status/"
        )

        self.assertEqual(response.status_code, 401)
