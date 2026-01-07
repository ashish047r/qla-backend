from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import UserProfile
from tracker.models import Company


# =========================================================
# TEST CASE 1 — GetVisitDataView
# =========================================================

class GetVisitDataViewTest(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username="visit_user@test.com",
            password="testpass123",
            is_active=True
        )

        self.profile, _ = UserProfile.objects.get_or_create(
            user=self.user,
            defaults={
                "pixel_id": "pixel_123",
                "company_name": "Fallback Company"
            }
        )

        self.client.force_authenticate(user=self.user)

        self.url = "/api/tracker/get_visit_data/"

    # =====================================================
    # TEST CASE 1: Success (no filters)
    # =====================================================
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
        self.assertEqual(response.data["success"], True)
        self.assertEqual(len(response.data["visits"]), 1)

    # =====================================================
    # TEST CASE 2: Filter by ad_type = google_ads
    # =====================================================
    def test_get_visit_data_filter_google_ads(self):
        Company.objects.create(
            user=self.user,
            company_name="Google Co",
            domain="google.com",
            url_visited="https://google.com",
            click_id="gclid123",
            ad_type="google_ads",
            ip_address="1.1.1.1",
        )

        Company.objects.create(
            user=self.user,
            company_name="Facebook Co",
            domain="fb.com",
            url_visited="https://fb.com",
            click_id="fbclid123",
            ad_type="facebook_ads",
            ip_address="2.2.2.2",
        )

        response = self.client.get(self.url, {"ad_type": "google_ads"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["visits"]), 1)
        self.assertEqual(response.data["visits"][0]["ad_type"], "google_ads")

    # =====================================================
    # TEST CASE 3: Invalid date format
    # =====================================================
    def test_get_visit_data_invalid_date_format(self):
        response = self.client.get(
            self.url,
            {"start_date": "2024-99-99", "end_date": "2024-10-10"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"error": "Invalid date format. Should be YYYY-MM-DD."}
        )

    # =====================================================
    # TEST CASE 4: Date range filter
    # =====================================================
    def test_get_visit_data_date_range(self):
        Company.objects.create(
            user=self.user,
            company_name="Date Test",
            domain="date.com",
            url_visited="https://date.com",
            click_id="date123",
            ad_type="google_ads",
            ip_address="3.3.3.3",
        )

        response = self.client.get(
            self.url,
            {"start_date": "2020-01-01", "end_date": "2030-01-01"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["success"], True)
        self.assertGreaterEqual(len(response.data["visits"]), 1)

    # =====================================================
    # TEST CASE 5: Unauthenticated request (DRF enforced)
    # =====================================================
    def test_get_visit_data_unauthenticated(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.data["detail"],
            "Authentication credentials were not provided."
        )








from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch, MagicMock

from accounts.models import UserProfile
from tracker.models import Company, IpInfo


# =========================================================
# TEST CASE 2 — SendVisitDataView
# =========================================================

class SendVisitDataViewTest(TestCase):

    @patch('accounts.signals.generate_profile_pixel')
    def setUp(self, mock_signal):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username="sendvisit@test.com",
            password="testpass123",
            is_active=True
        )

        self.profile, _ = UserProfile.objects.get_or_create(
            user=self.user,
            defaults={
                "pixel_id": "pixel_123",
                "company_name": "Fallback Company"
            }
        )
        # Ensure pixel_id is set even if profile already existed
        if not self.profile.pixel_id:
            self.profile.pixel_id = "pixel_123"
            self.profile.save()

        self.url = "/api/tracker/send_visit_data/"

    # =====================================================
    # TEST CASE 1: Missing pixel_id
    # =====================================================
    def test_send_visit_data_missing_pixel_id(self):
        payload = {
            "url": "https://example.com?gclid=abc",
            "ip": "1.1.1.1"
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"error": "Missing pixel_id."})

    # =====================================================
    # TEST CASE 2: Missing URL
    # =====================================================
    def test_send_visit_data_missing_url(self):
        payload = {
            "id": "pixel_123",
            "ip": "1.1.1.1"
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"error": "Missing URL."})

    # =====================================================
    # TEST CASE 3: Missing IP
    # =====================================================
    def test_send_visit_data_missing_ip(self):
        payload = {
            "id": "pixel_123",
            "url": "https://example.com"
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"error": "Missing IP."})

    # =====================================================
    # TEST CASE 4: Snitcher API request failure
    # =====================================================
    @patch("tracker.pixel.requests.post")
    def test_send_visit_data_snitcher_exception(self, mock_post):
        mock_post.side_effect = Exception("Boom")

        payload = {
            "id": "pixel_123",
            "url": "https://example.com?gclid=abc",
            "ip": "1.1.1.1"
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(
            response.data,
            {"error": "Failed to reach Snitcher API."}
        )

    # =====================================================
    # TEST CASE 5: Snitcher returns 202 (queued)
    # =====================================================
    @patch("tracker.pixel.requests.post")
    def test_send_visit_data_snitcher_queued(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_post.return_value = mock_response

        payload = {
            "id": "pixel_123",
            "url": "https://example.com?gclid=abc",
            "ip": "1.1.1.1"
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.data,
            {"error": "Enrichment queued. Please retry shortly."}
        )

    # =====================================================
    # TEST CASE 6: Snitcher returns 404 (company not found)
    # =====================================================
    @patch("tracker.pixel.requests.post")
    def test_send_visit_data_snitcher_not_found(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_post.return_value = mock_response

        payload = {
            "id": "pixel_123",
            "url": "https://example.com?gclid=abc",
            "ip": "1.1.1.1"
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.data,
            {"error": "Company not identified for this IP."}
        )

        self.assertTrue(IpInfo.objects.filter(ip_address="1.1.1.1").exists())

    # =====================================================
    # TEST CASE 7: Successful visit creation
    # =====================================================
    @patch("tracker.pixel.requests.get")
    @patch("tracker.pixel.requests.post")
    def test_send_visit_data_success(self, mock_post, mock_get):
        # ---- Snitcher success ----
        snitcher_resp = MagicMock()
        snitcher_resp.status_code = 200
        snitcher_resp.json.return_value = {
            "company": {
                "name": "Test Company",
                "website": "test.com",
                "employee_range": "1-10",
                "annual_revenue": "100000"
            },
            "geoIP": {"country_code": "US"}
        }
        mock_post.return_value = snitcher_resp

        # ---- CompanyEnrich success ----
        enrich_resp = MagicMock()
        enrich_resp.json.return_value = {"logo_url": "logo.png"}
        mock_get.return_value = enrich_resp

        payload = {
            "id": "pixel_123",
            "url": "https://example.com?gclid=abc&utm_source=test",
            "ip": "1.1.1.1"
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"success": True})

        # ---- DB assertions ----
        self.assertTrue(Company.objects.filter(click_id="abc").exists())
        self.assertTrue(IpInfo.objects.filter(ip_address="1.1.1.1", status="Found").exists())





from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch, MagicMock

from accounts.models import UserProfile
from google_ads.models import GoogleAdsProject


# =========================================================
# TEST CASE 3 — SetGoogleConversionEventView
# =========================================================

class SetGoogleConversionEventViewTest(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username="setgoogle@test.com",
            password="testpass123",
            is_active=True
        )

        self.profile, _ = UserProfile.objects.get_or_create(
    user=self.user,
    defaults={
        "pixel_id": "pixel_123",
        "company_name": "Fallback Company"
    }
)

        self.client.force_authenticate(user=self.user)

        self.url = "/api/tracker/set_google_conversion_event/"

    # =====================================================
    # TEST CASE 1: GoogleAdsProject missing
    # =====================================================
    def test_set_google_conversion_fails_if_google_project_missing(self):
        payload = {
            "type": "set",
            "resource_name": "customers/123/conversionActions/456",
            "descriptive_name": "Test Conversion",
            "category_name": "PURCHASE"
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.data,
            {"error": "Google Ads project not found for user."}
        )

    # =====================================================
    # TEST CASE 2: Set existing conversion action
    # =====================================================
    @patch("tracker.conversions.GoogleAdsClient.load_from_dict")
    def test_set_google_conversion_existing(self, mock_google_client):
        GoogleAdsProject.objects.create(
            user=self.user,
            refresh_token="fake_refresh",
            customer_id="1234567890",
            manager_id="987654321"
        )

        payload = {
            "type": "set",
            "resource_name": "customers/123/conversionActions/999",
            "descriptive_name": "My Conversion",
            "category_name": "PURCHASE"
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "success": True,
                "resource_name": "customers/123/conversionActions/999",
                "descriptive_name": "My Conversion",
                "category_name": "PURCHASE",
            }
        )

        gt = GoogleAdsProject.objects.get(user=self.user)
        self.assertEqual(gt.conversion_action_resource_name, payload["resource_name"])
        self.assertEqual(gt.conversion_action_descriptive_name, payload["descriptive_name"])
        self.assertEqual(gt.conversion_action_category_name, payload["category_name"])

    # =====================================================
    # TEST CASE 3: Create new conversion action
    # =====================================================
    @patch("tracker.conversions.create_google_ads_custom_conversion")
    @patch("tracker.conversions.GoogleAdsClient.load_from_dict")
    def test_set_google_conversion_new(self, mock_google_client, mock_create_conversion):
        GoogleAdsProject.objects.create(
            user=self.user,
            refresh_token="fake_refresh",
            customer_id="1234567890",
            manager_id="987654321"
        )

        mock_create_conversion.return_value = {
            "resource_name": "customers/123/conversionActions/111",
            "descriptive_name": "New Conversion",
            "category_name": "LEAD",
        }

        payload = {
            "type": "new",
            "resource_name": "",
            "descriptive_name": "New Conversion",
            "category_name": "LEAD"
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "success": True,
                "resource_name": "customers/123/conversionActions/111",
                "descriptive_name": "New Conversion",
                "category_name": "LEAD",
            }
        )

        gt = GoogleAdsProject.objects.get(user=self.user)
        self.assertEqual(gt.conversion_action_descriptive_name, "New Conversion")
        self.assertEqual(gt.conversion_action_category_name, "LEAD")

    # =====================================================
    # TEST CASE 4: Invalid request type
    # =====================================================
    @patch("tracker.conversions.GoogleAdsClient.load_from_dict")
    def test_set_google_conversion_invalid_type(self, mock_google_client):
        GoogleAdsProject.objects.create(
            user=self.user,
            refresh_token="fake_refresh",
            customer_id="1234567890",
            manager_id="987654321"
        )

        payload = {
            "type": "invalid",
            "resource_name": "",
            "descriptive_name": "",
            "category_name": ""
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {
                "success": False,
                "resource_name": "",
                "descriptive_name": "",
            }
        )



from django.test import TestCase
from rest_framework.test import APIClient
from unittest.mock import patch

# =========================================================
# TEST CASE 4 — GetPixelData (Webhook)
# =========================================================

class GetPixelDataWebhookTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = "/api/tracker/webhook/"

    # =====================================================
    # TEST CASE 1: Webhook succeeds with valid payload
    # =====================================================
    @patch("tracker.webhooks.handle_company_visit")
    @patch("tracker.webhooks.extract_tracking_data")
    def test_webhook_success_with_valid_payload(
        self,
        mock_extract_tracking_data,
        mock_handle_company_visit
    ):
        payload = {
            "internal_identifier": "testuser@test.com",
            "events": [
                {
                    "event_name": "pageview",
                    "created_at": "2024-01-01T10:00:00Z",
                    "context": {
                        "geo": {"ip": "1.2.3.4"},
                        "page": {"url": "https://example.com/?gclid=abc123"},
                        "user_agent": "Mozilla"
                    }
                }
            ]
        }

        mock_extract_tracking_data.return_value = {
            "internal_identifier": "testuser@test.com",
            "ip": "1.2.3.4",
            "clid": "abc123",
            "ad_type": "google_ads",
            "url": "https://example.com/?gclid=abc123"
        }

        response = self.client.post(
            self.url,
            payload,
            format="json"
        )

        # ---- response ----
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data)  # Response(status=200)

        # ---- helpers called ----
        mock_extract_tracking_data.assert_called_once_with(payload)
        mock_handle_company_visit.assert_called_once()

        # ---- ensure raw_payload injected ----
        args, kwargs = mock_handle_company_visit.call_args
        self.assertIn("raw_payload", args[0])

    # =====================================================
    # TEST CASE 2: Webhook succeeds but extract_tracking_data returns None
    # =====================================================
    @patch("tracker.webhooks.handle_company_visit")
    @patch("tracker.webhooks.extract_tracking_data")
    def test_webhook_success_with_unparseable_payload(
        self,
        mock_extract_tracking_data,
        mock_handle_company_visit
    ):
        payload = {
            "internal_identifier": "testuser@test.com",
            "events": []
        }

        mock_extract_tracking_data.return_value = None

        response = self.client.post(
            self.url,
            payload,
            format="json"
        )

        # ---- response ----
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data)

        # ---- extract called, handler NOT called ----
        mock_extract_tracking_data.assert_called_once_with(payload)
        mock_handle_company_visit.assert_not_called()

    # =====================================================
    # TEST CASE 3: Webhook with completely empty payload
    # =====================================================
    @patch("tracker.webhooks.handle_company_visit")
    @patch("tracker.webhooks.extract_tracking_data")
    def test_webhook_with_empty_payload(
        self,
        mock_extract_tracking_data,
        mock_handle_company_visit
    ):
        payload = {}

        mock_extract_tracking_data.return_value = None

        response = self.client.post(
            self.url,
            payload,
            format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data)

        mock_extract_tracking_data.assert_called_once_with(payload)
        mock_handle_company_visit.assert_not_called()
