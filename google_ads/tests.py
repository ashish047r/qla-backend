from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from unittest.mock import patch, MagicMock

from google_ads.models import GoogleAdsProject


class GoogleAdsGetUrlTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123"
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)  #Pretend every request is coming from this logged-in user.”

    @patch("google_ads.views.Flow.from_client_secrets_file")
    def test_get_oauth_url(self, mock_flow):
        # ---- mock Google OAuth flow ----
        mock_flow_instance = MagicMock()
        mock_flow.return_value = mock_flow_instance

        mock_flow_instance.authorization_url.return_value = (
            "https://accounts.google.com/o/oauth2/auth",
            "dummy_state"
        )

        # ---- call API ----
        response = self.client.get("/api/google-ads/get-url/")

        # ---- assertions ----
        self.assertEqual(response.status_code, 200)
        self.assertIn("authorization_url", response.data)
        self.assertTrue(response.data["authorization_url"])




# =========================================================
# TEST CASE 2
# =========================================================

class GoogleAdsGetTokenTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser2",
            password="testpass123"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)  #Authorization: Bearer <valid-token>


    @patch("google_ads.views.Flow.from_client_secrets_file") #Real function opens secrets.json #Unit tests must never do that.
    def test_get_token_saves_refresh_token(self, mock_flow):
        # ---- mock OAuth flow ----
        mock_flow_instance = MagicMock()
        mock_flow.return_value = mock_flow_instance

        # fake credentials object
        mock_credentials = MagicMock()
        mock_credentials.refresh_token = "fake_refresh_token_123"
        mock_flow_instance.credentials = mock_credentials

        # fetch_token should do nothing (but not fail)
        mock_flow_instance.fetch_token.return_value = None

        # ---- call API ----
        payload = {
            "google_access_code": "fake_auth_code"
        }

        response = self.client.post(
            "/api/google-ads/get-token/",
            payload,
            format="json"
        )

        # ---- assertions ----
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["connected"])

        # ---- DB assertion ----
        google_obj = GoogleAdsProject.objects.get(user=self.user)
        self.assertEqual(google_obj.refresh_token, "fake_refresh_token_123")




# =========================================================
# TEST CASE 3
# =========================================================

class GoogleAdsListClientsTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser3",
            password="testpass123"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # user already has Google Ads connected
        GoogleAdsProject.objects.create(
            user=self.user,
            refresh_token="fake_refresh_token"
        )

    @patch("google_ads.services.google_ads_client.GoogleAdsClient.load_from_dict")
    def test_list_clients_returns_accounts(self, mock_google_client):
        # ---- mock Google Ads client ----
        mock_client_instance = MagicMock()
        mock_google_client.return_value = mock_client_instance

        # ---- mock CustomerService ----
        mock_customer_service = MagicMock()
        mock_customer_service.list_accessible_customers.return_value.resource_names = [
            "customers/1234567890"
        ]

        # ---- mock GoogleAdsService ----
        mock_ga_service = MagicMock()

        # fake row returned by GAQL
        mock_row = MagicMock()
        mock_row.customer_client.descriptive_name = "Test Account"
        mock_row.customer_client.id = 1234567890
        mock_row.customer_client.resource_name = "customers/999/customers/1234567890"

        # search_stream returns batches → rows
        mock_batch = MagicMock()
        mock_batch.results = [mock_row]
        mock_ga_service.search_stream.return_value = [mock_batch]

        # ---- attach services to client ----
        def get_service(name):
            if name == "CustomerService":
                return mock_customer_service
            if name == "GoogleAdsService":
                return mock_ga_service

        mock_client_instance.get_service.side_effect = get_service

        # ---- call API ----
        response = self.client.get("/api/google-ads/list-clients/")

        # ---- assertions ----
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

        account = response.data[0]
        self.assertEqual(account["description"], "Test Account")
        self.assertEqual(account["customer_id"], 1234567890)





# =========================================================
# TEST CASE 4 — ConnectAccountView
# =========================================================

class GoogleAdsConnectAccountTest(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username="connect_user@test.com",
            password="pepperoni12",
            is_active=True
        )

        self.client.force_authenticate(user=self.user)

        # ---- Google Ads token already exists ----
        self.google_project = GoogleAdsProject.objects.create(
            user=self.user,
            refresh_token="fake_refresh_token"
        )

    # =====================================================
    # TEST CASE 1: Connect account succeeds
    # =====================================================
    def test_connect_account_success(self):
        payload = {
            "customer_id": "1234567890",
            "customer_name": "Test Google Ads Account",
            "manager_id": "987654321"
        }

        response = self.client.post(
            "/api/google-ads/connect-account/",
            payload,
            format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"message": "Customer ID attached successfully."}
        )

        # ---- DB validation ----
        self.google_project.refresh_from_db()
        self.assertEqual(self.google_project.customer_id, "1234567890")
        self.assertEqual(self.google_project.customer_name, "Test Google Ads Account")

        # ✅ FIX: manager_id is IntegerField
        self.assertEqual(self.google_project.manager_id, 987654321)

    # =====================================================
    # TEST CASE 2: Connect account fails if token not created
    # =====================================================
    def test_connect_account_fails_if_google_project_missing(self):
        # ---- remove GoogleAdsProject ----
        self.google_project.delete()

        payload = {
            "customer_id": "1234567890",
            "customer_name": "Test Google Ads Account",
            "manager_id": "987654321"
        }

        # ✅ FIX: Django re-raises uncaught exceptions in tests
        with self.assertRaises(GoogleAdsProject.DoesNotExist):
            self.client.post(
                "/api/google-ads/connect-account/",
                payload,
                format="json"
            )



# =========================================================
# TEST CASE 5 — DetachAccountView
# =========================================================

class GoogleAdsDetachAccountTest(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username="detach_user@test.com",
            password="pepperoni12",
            is_active=True
        )

        self.client.force_authenticate(user=self.user)

        # ---- Google Ads project exists ----
        self.google_project = GoogleAdsProject.objects.create(
            user=self.user,
            refresh_token="fake_refresh_token",
            customer_id="1234567890"
        )

    # =====================================================
    # TEST CASE 1: Detach account succeeds
    # =====================================================
    def test_detach_account_success(self):
        response = self.client.get("/api/google-ads/detach-account/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"message": "Customer ID detached successfully."}
        )

        # ---- DB validation ----
        self.assertFalse(
            GoogleAdsProject.objects.filter(user=self.user).exists()
        )

    # =====================================================
    # TEST CASE 2: Detach account fails if GoogleAdsProject missing
    # =====================================================
    def test_detach_account_fails_if_google_project_missing(self):
        # ---- remove GoogleAdsProject ----
        self.google_project.delete()

        # ✅ FIX: expect exception, not response
        with self.assertRaises(GoogleAdsProject.DoesNotExist):
            self.client.get("/api/google-ads/detach-account/")
