# QLA Backend
Django 5.2 service for tracking website visits via an embedded pixel, enriching IP/company data, and syncing conversions to Google Ads, Facebook Ads, and HubSpot. The project exposes a REST API (DRF + JWT) and ships with a lightweight SQLite database for local use.

## Quick start
1) Python 3.10+ recommended.  
2) Create a virtualenv and install deps:
```
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```
If `pip install` fails because of encoding artefacts in `requirements.txt`, open/re-save it as UTF-8 and retry.
3) Run migrations and create an admin user:
```
python manage.py migrate
python manage.py createsuperuser
```
4) Start the API:
```
python manage.py runserver
```

## Configuration
Defaults live in `pixel_tracker/settings.py` and include real secrets; override them with environment variables before deploying:
- `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`
- Email SMTP credentials (`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, etc.)
- Redirects and public URLs (`PUBLIC_BASE_URL`, `REDIRECT_URI`, `HUBSPOT_REDIRECT_URI`)
- Third-party keys: Facebook (`FB_APP_ID`, `FB_APP_SECRET`), Google Ads (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_DEVELOPER_TOKEN`, `GOOGLE_CLIENT_SECRET_PATH`), HubSpot (`HUBSPOT_CLIENT_ID`, `HUBSPOT_CLIENT_SECRET`, `HUBSPOT_OAUTH_SCOPES`), IP/company enrichment keys, and any API keys used in the tracker views.
- Database: defaults to SQLite (`db.sqlite3`). Point `DATABASES` to Postgres/MySQL for production.

## Apps and responsibilities
- `accounts`: signup/login (JWT), activation + password reset emails, and `UserProfile` (stores `pixel_id`, `company_name`, up to five `company_domains`).
- `tracker`: pixel verification, visit ingestion (`send_visit_data`), visit retrieval with filters, and conversion uploads to ad platforms. Models include `CompanyVisit` and `IpInfo`.
- `google_ads`: OAuth + account selection, storing refresh tokens/customer IDs (`GoogleAdsProject`).
- `facebook_ads`: OAuth + ad account selection and conversion actions (`FacebookAdsProject`).
- `hubspot`: OAuth flow and contact lookup/enrichment (`HubspotProject`).

## API map (prefix `/api/`)
- Accounts (`/accounts/`): `signup/`, `activate/<uid>/<token>/`, `login/`, `token/refresh/`, `forgot-password/`, `reset-password/<uid>/<token>/`, `get-user-info/`, `user-profile/`, `integrations-status/`, `logout/`.
- Tracker (`/tracker/`): `verify_pixel/`, `send_visit_data/`, `get_visit_data/?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&ad_type=google_ads|facebook_ads`, `visit_to_google_ads_conversion/`, `visit_to_facebook_ads_conversion/`, `set_google_conversion_event/`, `set_facebook_conversion_event/`.
- Google Ads (`/google-ads/`): `get-url/`, `get-token/`, `connect-account/`, `detach-account/`, `list-clients/`, `get-credentials/`.
- Facebook Ads (`/facebook-ads/`): `get-url/`, `get-token/`, `connect-account/`, `detach-account/`, `list-clients/`, `get-credentials/`, `list-conversion-actions/`.
- HubSpot (`/hubspot/`): `get-url/`, `callback/`, `refresh/`, `search-contact/`.

## Typical flow
1) User signs up, receives activation email, logs in, and obtains a JWT.  
2) `UserProfile.pixel_id` is embedded in the site’s pixel script; the frontend calls `tracker/send_visit_data/` with `id`, `url`, and `ip`.  
3) Backend enriches the IP → company data, records a `CompanyVisit`, and deduplicates visits by `click_id`.  
4) When a visit converts, client code calls `visit_to_google_ads_conversion/` or `visit_to_facebook_ads_conversion/` with the click IDs and conversion values to push events to the ad platforms.  
5) Optional: connect Google Ads, Facebook Ads, and HubSpot via their respective `/get-url/` → `/get-token/` flows to persist refresh tokens/accounts.

## Development notes
- Admin site available at `/admin/` once a superuser exists.
- Tests: none included; run `python manage.py test` to execute any you add.
- Sample API docs for HubSpot live in `hubspot/api.txt`; integration helpers live alongside each app.
- Be mindful of committed secrets in `pixel_tracker/settings.py`—rotate them and move to environment variables before shipping.
