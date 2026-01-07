from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from unittest.mock import patch, MagicMock


class GetUrlIntegrationTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="url@test.com",
            password="test123",
            is_active=True
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("google_ads.views.Flow.from_client_secrets_file")
    def test_get_url_success(self, mock_flow):
        # ---- mock Google OAuth flow ----
        mock_flow_instance = MagicMock()
        mock_flow.return_value = mock_flow_instance

        mock_flow_instance.authorization_url.return_value = (
            "https://accounts.google.com/o/oauth2/auth",
            "state123"
        )

        response = self.client.get("/api/google-ads/get-url/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("authorization_url", response.data)
        self.assertIn("passthrough_val", response.data)




from google_ads.models import GoogleAdsProject


class GetTokenIntegrationTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="token@test.com",
            password="test123",
            is_active=True
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("google_ads.views.Flow.from_client_secrets_file")
    def test_get_token_creates_google_project(self, mock_flow):
        # ---- mock OAuth flow ----
        mock_flow_instance = MagicMock()
        mock_flow.return_value = mock_flow_instance

        mock_credentials = MagicMock()
        mock_credentials.refresh_token = "fake_refresh_token"
        mock_flow_instance.credentials = mock_credentials
        mock_flow_instance.fetch_token.return_value = None

        response = self.client.post(
            "/api/google-ads/get-token/",
            {"google_access_code": "fake_code"},
            format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["connected"])

        google_obj = GoogleAdsProject.objects.get(user=self.user)
        self.assertEqual(google_obj.refresh_token, "fake_refresh_token")



class ConnectAccountIntegrationTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="connect@test.com",
            password="test123",
            is_active=True
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.google_project = GoogleAdsProject.objects.create(
            user=self.user,
            refresh_token="fake_refresh_token"
        )

    def test_connect_account_success(self):
        payload = {
            "customer_id": "1234567890",
            "customer_name": "My Google Ads",
            "manager_id": 999999
        }

        response = self.client.post(
            "/api/google-ads/connect-account/",
            payload,
            format="json"
        )

        self.assertEqual(response.status_code, 200)

        self.google_project.refresh_from_db()
        self.assertEqual(self.google_project.customer_id, "1234567890")
        self.assertEqual(self.google_project.customer_name, "My Google Ads")
        self.assertEqual(self.google_project.manager_id, 999999)



class DetachAccountIntegrationTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="detach@test.com",
            password="test123",
            is_active=True
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.google_project = GoogleAdsProject.objects.create(
            user=self.user,
            refresh_token="fake_refresh_token",
            customer_id="123"
        )

    def test_detach_account_success(self):
        response = self.client.get("/api/google-ads/detach-account/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            GoogleAdsProject.objects.filter(user=self.user).exists()
        )
