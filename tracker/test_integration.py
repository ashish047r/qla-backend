from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch, MagicMock

from accounts.models import UserProfile
from tracker.models import Company, IpInfo
from google_ads.models import GoogleAdsProject


# =========================================================
# 1️⃣ GetVisitDataView Integration Tests
# =========================================================

class GetVisitDataIntegrationTest(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username="visit@test.com",
            password="pass123",
            is_active=True
        )

        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.pixel_id = "pixel_123"
        profile.company_name = "Fallback Co"
        profile.save()

        self.client.force_authenticate(user=self.user)
        self.url = "/api/tracker/get_visit_data/"

    def test_get_visit_data_success(self):
        Company.objects.create(
            user=self.user,
            company_name="Test Company",
            domain="example.com",
            url_visited="https://example.com",
            click_id="gclid123",
            ad_type="google_ads",
            ip_address="1.1.1.1",
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(len(response.data["visits"]), 1)

    def test_get_visit_data_filter_google_ads(self):
        Company.objects.create(
            user=self.user,
            company_name="Google Co",
            domain="google.com",
            url_visited="https://google.com",
            click_id="gclid1",
            ad_type="google_ads",
            ip_address="1.1.1.1",
        )

        Company.objects.create(
            user=self.user,
            company_name="FB Co",
            domain="fb.com",
            url_visited="https://fb.com",
            click_id="fbclid1",
            ad_type="facebook_ads",
            ip_address="2.2.2.2",
        )

        response = self.client.get(self.url, {"ad_type": "google_ads"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["visits"]), 1)
        self.assertEqual(response.data["visits"][0]["ad_type"], "google_ads")

    def test_get_visit_data_invalid_date(self):
        response = self.client.get(self.url, {
            "start_date": "2024-99-99",
            "end_date": "2024-10-10"
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"error": "Invalid date format. Should be YYYY-MM-DD."}
        )

    def test_get_visit_data_unauthenticated(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.data["detail"],
            "Authentication credentials were not provided."
        )


# =========================================================
# 2️⃣ SendVisitDataView Integration Tests
# =========================================================

class SendVisitDataIntegrationTest(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username="send@test.com",
            password="pass123",
            is_active=True
        )

        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.pixel_id = "pixel_123"
        profile.company_name = "Fallback Co"
        profile.save()

        self.url = "/api/tracker/send_visit_data/"

    def test_missing_pixel_id(self):
        response = self.client.post(self.url, {
            "url": "https://example.com",
            "ip": "1.1.1.1"
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"error": "Missing pixel_id."})

    def test_missing_url(self):
        response = self.client.post(self.url, {
            "id": "pixel_123",
            "ip": "1.1.1.1"
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"error": "Missing URL."})

    def test_missing_ip(self):
        response = self.client.post(self.url, {
            "id": "pixel_123",
            "url": "https://example.com"
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"error": "Missing IP."})

    @patch("tracker.pixel.requests.post")
    def test_snitcher_exception(self, mock_post):
        mock_post.side_effect = Exception("Boom")

        response = self.client.post(self.url, {
            "id": "pixel_123",
            "url": "https://example.com?gclid=abc",
            "ip": "1.1.1.1"
        }, format="json")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.data,
            {"error": "Failed to reach Snitcher API."}
        )

    @patch("tracker.pixel.requests.post")
    @patch("tracker.pixel.requests.get")
    def test_send_visit_data_success(self, mock_get, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "company": {
                "name": "Test Company",
                "website": "test.com",
                "employee_range": "1-10",
                "annual_revenue": "1000"
            },
            "geoIP": {"country_code": "US"}
        }

        mock_get.return_value.json.return_value = {
            "logo_url": "logo.png"
        }

        response = self.client.post(self.url, {
            "id": "pixel_123",
            "url": "https://example.com?gclid=abc",
            "ip": "1.1.1.1"
        }, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Company.objects.filter(click_id="abc").exists())
        self.assertTrue(IpInfo.objects.filter(ip_address="1.1.1.1").exists())


# =========================================================
# 3️⃣ SetGoogleAdsConversionEventView Integration Tests
# =========================================================

class SetGoogleAdsConversionIntegrationTest(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username="google@test.com",
            password="pass123",
            is_active=True
        )

        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.pixel_id = "pixel_123"
        profile.company_name = "Fallback Co"
        profile.save()

        self.client.force_authenticate(user=self.user)
        self.url = "/api/tracker/set_google_conversion_event/"

    def test_google_project_missing(self):
        response = self.client.post(self.url, {
            "type": "set",
            "resource_name": "x",
            "descriptive_name": "y",
            "category_name": "PURCHASE"
        }, format="json")

        self.assertEqual(response.status_code, 404)

    @patch("tracker.conversions.GoogleAdsClient.load_from_dict")
    def test_set_existing_conversion(self, mock_client):
        GoogleAdsProject.objects.create(
            user=self.user,
            refresh_token="r",
            customer_id="123",
            manager_id="456"
        )

        response = self.client.post(self.url, {
            "type": "set",
            "resource_name": "customers/1/conversionActions/1",
            "descriptive_name": "My Conversion",
            "category_name": "PURCHASE"
        }, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])


# =========================================================
# 4️⃣ GetPixelData (Webhook) Integration Tests
# =========================================================

class GetPixelDataWebhookIntegrationTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = "/api/tracker/webhook/"

    @patch("tracker.webhooks.handle_company_visit")
    @patch("tracker.webhooks.extract_tracking_data")
    def test_webhook_success(self, mock_extract, mock_handle):
        mock_extract.return_value = {
            "internal_identifier": "test@test.com",
            "ip": "1.2.3.4",
            "clid": "abc",
            "ad_type": "google_ads",
            "url": "https://example.com?gclid=abc"
        }

        payload = {
            "events": [{"created_at": "2024-01-01T10:00:00Z"}]
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, 200)
        mock_extract.assert_called_once()
        mock_handle.assert_called_once()

    @patch("tracker.webhooks.extract_tracking_data")
    def test_webhook_unparseable_payload(self, mock_extract):
        mock_extract.return_value = None

        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 200)
