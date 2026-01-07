from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from unittest.mock import patch, MagicMock

from facebook_ads.models import FacebookAdsProject


# =========================================================
# TEST CASE 1
# Authenticated user can get Facebook OAuth URL
# =========================================================

class FacebookAdsGetUrlTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="fb_user_1",
            password="testpass123"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_get_facebook_oauth_url(self):
        response = self.client.get("/api/facebook-ads/get-url/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("authorization_url", response.json())
        self.assertTrue(response.json()["authorization_url"])


# =========================================================
# TEST CASE 2
# Facebook token exchange stores access token
# =========================================================

class FacebookAdsGetTokenTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="fb_user_2",
            password="testpass123"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("facebook_ads.views.requests.get")
    def test_get_token_saves_access_token(self, mock_requests_get):
        # ---- mock Facebook token API ----
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "fake_fb_access_token_123"
        }
        mock_requests_get.return_value = mock_response

        payload = {
            "code": "fake_facebook_auth_code"
        }

        response = self.client.post(
            "/api/facebook-ads/get-token/",
            payload,
            format="json"
        )

        self.assertEqual(response.status_code, 200)

        fb_obj = FacebookAdsProject.objects.get(user=self.user)
        self.assertEqual(fb_obj.access_token, "fake_fb_access_token_123")


# =========================================================
# TEST CASE 3
# Connected user can list Facebook ad accounts
# =========================================================

class FacebookAdsListClientsTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="fb_user_3",
            password="testpass123"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # User already connected to Facebook Ads
        FacebookAdsProject.objects.create(
            user=self.user,
            access_token="fake_fb_access_token"
        )

    @patch("facebook_ads.views.requests.get")
    def test_list_clients_returns_accounts(self, mock_requests_get):
        # ---- mock Facebook ad accounts API ----
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "111", "name": "Test Ad Account 1"},
                {"id": "222", "name": "Test Ad Account 2"},
            ]
        }
        mock_requests_get.return_value = mock_response

        response = self.client.get("/api/facebook-ads/list-clients/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

        self.assertEqual(response.json()[0]["id"], "111")
        self.assertEqual(response.json()[0]["name"], "Test Ad Account 1")




class FacebookAdsConnectAccountTest(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username="fb_connect_user@test.com",
            password="pepperoni12",
            is_active=True
        )

        self.client.force_authenticate(user=self.user)

        # ---- Facebook Ads token already exists (from GetTokenView) ----
        self.fb_project = FacebookAdsProject.objects.create(
            user=self.user,
            access_token="fake_fb_access_token"
        )

    # =====================================================
    # TEST CASE 1: Connect account succeeds
    # =====================================================
    def test_connect_account_success(self):
        payload = {
            "id": "act_1234567890",
            "name": "Test Facebook Ad Account"
        }

        response = self.client.post(
            "/api/facebook-ads/connect-account/",
            payload,
            format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"message": "Facebook ID attached successfully."}
        )

        # ---- DB validation ----
        self.fb_project.refresh_from_db()
        self.assertEqual(self.fb_project.customer_id, "act_1234567890")
        self.assertEqual(self.fb_project.customer_name, "Test Facebook Ad Account")

    # =====================================================
    # TEST CASE 2: Connect account fails if token not created
    # =====================================================
    def test_connect_account_fails_if_facebook_project_missing(self):
        # ---- remove FacebookAdsProject ----
        self.fb_project.delete()

        payload = {
            "id": "act_1234567890",
            "name": "Test Facebook Ad Account"
        }

        # ---- failure ----
        # View raises DoesNotExist → Django re-raises in tests
        with self.assertRaises(FacebookAdsProject.DoesNotExist):
            self.client.post(
                "/api/facebook-ads/connect-account/",
                payload,
                format="json"
            )




class FacebookAdsDetachAccountTest(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username="fb_detach_user@test.com",
            password="pepperoni12",
            is_active=True
        )

        self.client.force_authenticate(user=self.user)

        # ---- Facebook Ads project exists ----
        self.fb_project = FacebookAdsProject.objects.create(
            user=self.user,
            access_token="fake_fb_access_token",
            customer_id="act_1234567890"
        )

    # =====================================================
    # TEST CASE 1: Detach account succeeds
    # =====================================================
    def test_detach_account_success(self):
        response = self.client.get("/api/facebook-ads/detach-account/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"message": "Customer ID detached successfully."}
        )

        # ---- DB validation ----
        self.assertFalse(
            FacebookAdsProject.objects.filter(user=self.user).exists()
        )

    # =====================================================
    # TEST CASE 2: Detach account fails if FacebookAdsProject missing
    # =====================================================
    def test_detach_account_fails_if_facebook_project_missing(self):
        # ---- remove FacebookAdsProject ----
        self.fb_project.delete()

        # ---- failure ----
        with self.assertRaises(FacebookAdsProject.DoesNotExist):
            self.client.get("/api/facebook-ads/detach-account/")
