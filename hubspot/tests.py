from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from unittest.mock import patch

from hubspot.models import HubspotProject


# =========================================================
# TEST CASE 1 — GetUrlView
# =========================================================

class HubspotGetUrlTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="hubspot_geturl@test.com",
            password="pepperoni12",
            is_active=True
        )
        self.client.force_authenticate(user=self.user)

    def test_get_url_success(self):
        response = self.client.get("/api/hubspot/get-url/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("authorization_url", response.data)
        self.assertIn("state", response.data)


# =========================================================
# TEST CASE 2 — GetTokenView
# =========================================================

class HubspotGetTokenTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="hubspot_token@test.com",
            password="pepperoni12",
            is_active=True
        )
        self.client.force_authenticate(user=self.user)

    # =====================================================
    # TEST CASE 1: Token exchange succeeds
    # =====================================================
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

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["message"], "HubSpot Connected")

    # =====================================================
    # TEST CASE 2: Missing code
    # =====================================================
    def test_get_token_fails_if_code_missing(self):
        response = self.client.post(
            "/api/hubspot/get-token/",
            {},
            format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"error": "Missing code"})

    # =====================================================
    # TEST CASE 3: No auth + no state
    # =====================================================
    def test_get_token_fails_if_no_auth_and_no_state(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(
            "/api/hubspot/get-token/",
            {"code": "valid_code"},
            format="json"
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.data,
            {"detail": "Authentication credentials were not provided."}
        )


    # =====================================================
    # TEST CASE 4: State user mismatch
    # =====================================================
    @patch("hubspot.views.resolve_user_from_state")
    def test_get_token_fails_if_state_user_mismatch(self, mock_resolve):
        other_user = User.objects.create_user(
            username="other@test.com",
            password="test123"
        )

        mock_resolve.return_value = other_user

        response = self.client.post(
            "/api/hubspot/get-token/",
            {
                "state": "fake_state",
                "code": "valid_code"
            },
            format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"detail": "State token does not match authenticated user."}
        )

    # =====================================================
    # TEST CASE 5: exchange_code_for_tokens raises ValueError
    # =====================================================
    @patch("hubspot.views.exchange_code_for_tokens")
    def test_get_token_fails_on_value_error(self, mock_exchange):
        mock_exchange.side_effect = ValueError("Invalid OAuth")

        response = self.client.post(
            "/api/hubspot/get-token/",
            {"code": "bad_code"},
            format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"error": "Invalid OAuth"})

    # =====================================================
    # TEST CASE 6: exchange_code_for_tokens raises Exception
    # =====================================================
    @patch("hubspot.views.exchange_code_for_tokens")
    def test_get_token_fails_on_exception(self, mock_exchange):
        mock_exchange.side_effect = Exception("Boom")

        response = self.client.post(
            "/api/hubspot/get-token/",
            {"code": "bad_code"},
            format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "OAuth failed")


# =========================================================
# TEST CASE 3 — ConnectAccountView
# =========================================================

class HubspotConnectAccountTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="hubspot_connect@test.com",
            password="pepperoni12",
            is_active=True
        )
        self.client.force_authenticate(user=self.user)

        self.token = HubspotProject.objects.create(
            user=self.user,
            access_token="fake_access",
            refresh_token="fake_refresh"
        )

    # =====================================================
    # TEST CASE 1: Connect account succeeds
    # =====================================================
    def test_connect_account_success(self):
        response = self.client.post(
            "/api/hubspot/connect-account/",
            {
                "hubspot_account_id": "999",
                "hubspot_account_name": "Test HubSpot",
                "hubspot_user_name": "Test User"
            },
            format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"message": "HubSpot account details updated successfully."}
        )

        self.token.refresh_from_db()
        self.assertEqual(self.token.hubspot_account_id, "999")

    # =====================================================
    # TEST CASE 2: Missing hubspot_account_id
    # =====================================================
    def test_connect_account_fails_if_account_id_missing(self):
        response = self.client.post(
            "/api/hubspot/connect-account/",
            {},
            format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"error": "hubspot_account_id is required."}
        )

    # =====================================================
    # TEST CASE 3: HubSpot not connected
    # =====================================================
    def test_connect_account_fails_if_not_connected(self):
        self.token.delete()

        response = self.client.post(
            "/api/hubspot/connect-account/",
            {"hubspot_account_id": "999"},
            format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"error": "HubSpot account not connected."}
        )


# =========================================================
# TEST CASE 4 — DetachAccountView
# =========================================================

class HubspotDetachAccountTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="hubspot_detach@test.com",
            password="pepperoni12",
            is_active=True
        )
        self.client.force_authenticate(user=self.user)

        self.token = HubspotProject.objects.create(
            user=self.user,
            access_token="fake_access",
            refresh_token="fake_refresh"
        )

    # =====================================================
    # TEST CASE 1: Detach succeeds
    # =====================================================
    def test_detach_account_success(self):
        response = self.client.get("/api/hubspot/detach-account/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"message": "HubSpot account detached successfully."}
        )

        self.assertFalse(
            HubspotProject.objects.filter(user=self.user).exists()
        )

    # =====================================================
    # TEST CASE 2: Detach fails if not connected
    # =====================================================
    def test_detach_account_fails_if_not_connected(self):
        self.token.delete()

        response = self.client.get("/api/hubspot/detach-account/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"error": "HubSpot account not connected."}
        )
