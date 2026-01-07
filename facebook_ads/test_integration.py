from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from unittest.mock import patch, MagicMock

from facebook_ads.models import FacebookAdsProject


class FacebookGetUrlIntegrationTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="fb_url@test.com",
            password="test123",
            is_active=True
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_get_facebook_oauth_url(self):
        response = self.client.get("/api/facebook-ads/get-url/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("authorization_url", response.json())
        self.assertTrue(response.json()["authorization_url"])



class FacebookGetTokenIntegrationTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="fb_token@test.com",
            password="test123",
            is_active=True
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("facebook_ads.oauth.requests.get")
    def test_get_token_creates_facebook_project(self, mock_requests_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "fake_fb_access_token"
        }
        mock_requests_get.return_value = mock_response

        response = self.client.post(
            "/api/facebook-ads/get-token/",
            {"code": "fake_auth_code"},
            format="json"
        )

        self.assertEqual(response.status_code, 200)

        fb_obj = FacebookAdsProject.objects.get(user=self.user)
        self.assertEqual(fb_obj.access_token, "fake_fb_access_token")



class FacebookListClientsIntegrationTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="fb_list@test.com",
            password="test123",
            is_active=True
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        FacebookAdsProject.objects.create(
            user=self.user,
            access_token="fake_fb_access_token"
        )

    @patch("facebook_ads.accounts.requests.get")
    def test_list_clients_success(self, mock_requests_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "act_1", "name": "Ad Account 1"},
                {"id": "act_2", "name": "Ad Account 2"},
            ]
        }
        mock_requests_get.return_value = mock_response

        response = self.client.get("/api/facebook-ads/list-clients/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)
        self.assertEqual(response.json()[0]["id"], "act_1")


class FacebookConnectAccountIntegrationTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="fb_connect@test.com",
            password="test123",
            is_active=True
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.fb_project = FacebookAdsProject.objects.create(
            user=self.user,
            access_token="fake_fb_access_token"
        )

    def test_connect_account_success(self):
        payload = {
            "id": "act_123456",
            "name": "Test Facebook Account"
        }

        response = self.client.post(
            "/api/facebook-ads/connect-account/",
            payload,
            format="json"
        )

        self.assertEqual(response.status_code, 200)

        self.fb_project.refresh_from_db()
        self.assertEqual(self.fb_project.customer_id, "act_123456")
        self.assertEqual(self.fb_project.customer_name, "Test Facebook Account")


class FacebookDetachAccountIntegrationTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="fb_detach@test.com",
            password="test123",
            is_active=True
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.fb_project = FacebookAdsProject.objects.create(
            user=self.user,
            access_token="fake_fb_access_token",
            customer_id="act_123"
        )

    def test_detach_account_success(self):
        response = self.client.get("/api/facebook-ads/detach-account/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            FacebookAdsProject.objects.filter(user=self.user).exists()
        )
