from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch

from hubspot.models import HubspotProject


# =========================================================
# TEST 1 — GetUrlView
# =========================================================

class HubspotGetUrlIntegrationTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="geturl@test.com",
            password="pepperoni12",
            is_active=True
        )
        self.client.force_authenticate(user=self.user)

    def test_get_url_success(self):
        response = self.client.get("/api/hubspot/get-url/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("authorization_url", response.data)
        self.assertIn("state", response.data)
        self.assertTrue(response.data["authorization_url"].startswith("https://"))


# =========================================================
# TEST 2 — GetTokenView
# =========================================================

class HubspotGetTokenIntegrationTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="token@test.com",
            password="pepperoni12",
            is_active=True
        )
        self.client.force_authenticate(user=self.user)

    @patch("hubspot.views.exchange_code_for_tokens")
    def test_get_token_success(self, mock_exchange):
        mock_exchange.return_value = {
            "message": "HubSpot Connected",
            "hub_id": "123",
            "account_name": "Test Hub",
            "user_name": "Test User",
        }

        response = self.client.post(
            "/api/hubspot/get-token/",
            {"code": "valid_code"},
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "HubSpot Connected")

    def test_get_token_fails_if_code_missing(self):
        response = self.client.post("/api/hubspot/get-token/", {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {"error": "Missing code"})

    def test_get_token_fails_without_auth_and_state(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(
            "/api/hubspot/get-token/",
            {"code": "valid_code"}
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.data,
            {"detail": "Authentication credentials were not provided."}
        )


    @patch("hubspot.views.resolve_user_from_state")
    def test_get_token_fails_on_state_user_mismatch(self, mock_resolve):
        other_user = User.objects.create_user(
            username="other@test.com",
            password="test123"
        )

        mock_resolve.return_value = other_user

        response = self.client.post(
            "/api/hubspot/get-token/",
            {"state": "fake_state", "code": "valid_code"}
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {"detail": "State token does not match authenticated user."}
        )

    @patch("hubspot.views.exchange_code_for_tokens")
    def test_get_token_fails_on_value_error(self, mock_exchange):
        mock_exchange.side_effect = ValueError("Invalid OAuth")

        response = self.client.post(
            "/api/hubspot/get-token/",
            {"code": "bad_code"}
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {"error": "Invalid OAuth"})

    @patch("hubspot.views.exchange_code_for_tokens")
    def test_get_token_fails_on_exception(self, mock_exchange):
        mock_exchange.side_effect = Exception("Boom")

        response = self.client.post(
            "/api/hubspot/get-token/",
            {"code": "bad_code"}
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "OAuth failed")


# =========================================================
# TEST 3 — ConnectAccountView
# =========================================================

class HubspotConnectAccountIntegrationTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="connect@test.com",
            password="pepperoni12",
            is_active=True
        )
        self.client.force_authenticate(user=self.user)

        self.token = HubspotProject.objects.create(
            user=self.user,
            access_token="fake_access",
            refresh_token="fake_refresh"
        )

    def test_connect_account_success(self):
        response = self.client.post(
            "/api/hubspot/connect-account/",
            {
                "hubspot_account_id": "999",
                "hubspot_account_name": "Test Hub",
                "hubspot_user_name": "Test User"
            },
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.token.refresh_from_db()
        self.assertEqual(self.token.hubspot_account_id, "999")

    def test_connect_account_fails_if_account_id_missing(self):
        response = self.client.post("/api/hubspot/connect-account/", {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {"error": "hubspot_account_id is required."}
        )

    def test_connect_account_fails_if_not_connected(self):
        self.token.delete()

        response = self.client.post(
            "/api/hubspot/connect-account/",
            {"hubspot_account_id": "999"}
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {"error": "HubSpot account not connected."}
        )


# =========================================================
# TEST 4 — DetachAccountView
# =========================================================

class HubspotDetachAccountIntegrationTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="detach@test.com",
            password="pepperoni12",
            is_active=True
        )
        self.client.force_authenticate(user=self.user)

        self.token = HubspotProject.objects.create(
            user=self.user,
            access_token="fake_access",
            refresh_token="fake_refresh"
        )

    def test_detach_account_success(self):
        response = self.client.get("/api/hubspot/detach-account/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(
            HubspotProject.objects.filter(user=self.user).exists()
        )

    def test_detach_account_fails_if_not_connected(self):
        self.token.delete()

        response = self.client.get("/api/hubspot/detach-account/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {"error": "HubSpot account not connected."}
        )
