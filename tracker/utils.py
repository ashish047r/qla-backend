import logging
import requests
from urllib.parse import urlparse, parse_qs
from django.utils.dateparse import parse_datetime

from .models import Company, IpInfo, CompanyVisit
from accounts.models import UserProfile

logger = logging.getLogger(__name__)


def create_company(payload, user):
    logger.info("Creating company for user %s", user)

    try:
        user_profile = UserProfile.objects.get(user=user)
    except UserProfile.DoesNotExist:
        logger.error("User profile not found for user %s", user)
        return None

    url_visited = payload.get('url')
    ip_raw = payload.get('ip')
    ip = ip_raw.strip() if isinstance(ip_raw, str) else ip_raw

    if not url_visited or not ip:
        logger.error("Missing URL or IP for company creation")
        return None

    # Double-check existence here to avoid accidental duplicates in fast retries
    existing_company = Company.objects.filter(user=user, ip_address__iexact=ip).first()
    if existing_company:
        logger.info("Company already exists for IP %s (id=%s); reusing", ip, existing_company.id)
        return existing_company

    click_id = payload.get('clid') or "null"
    ad_type = payload.get('ad_type') or "unknown"

    parsed_url = urlparse(url_visited)
    query_params = parse_qs(parsed_url.query)

    root_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"

    logger.debug("Root URL: %s", root_url)
    logger.debug("Query params: %s", query_params)

    # Snitcher lookup
    headers = {
        "Authorization": "Bearer 512|3Mh7A3c0kwMBNskFzNOTXLulrQ770lpXtyoqj7ayc4969073",
        "Accept": "application/json",
    }

    logger.info("Calling Snitcher API for IP %s", ip)

    try:
        snitcher_resp = requests.post(
            f"https://api.snitcher.com/company/find?ip={ip}",
            headers=headers,
            timeout=10,
        )
    except requests.RequestException:
        logger.exception("Snitcher API request failed")
        return None

    logger.info("Snitcher response %s: %s", snitcher_resp.status_code, snitcher_resp.text)

    if snitcher_resp.status_code in [202, 404]:
        logger.warning("Snitcher did not return company data for IP %s", ip)
        # Always log the attempt in IpInfo, update if exists, else create
        ipinfo_obj, created = IpInfo.objects.get_or_create(
            ip_address=ip,
            defaults={
                "status": "Not Found",
                "domain": root_url,
                "company_name": user_profile.company_name,
                "click_id": click_id,
            }
        )
        if not created:
            # Update status and fill missing fields if needed
            ipinfo_obj.status = "Not Found"
            if not ipinfo_obj.domain:
                ipinfo_obj.domain = root_url
            if not ipinfo_obj.company_name:
                ipinfo_obj.company_name = user_profile.company_name
            if not ipinfo_obj.click_id:
                ipinfo_obj.click_id = click_id
            ipinfo_obj.save()
        return None

    if snitcher_resp.status_code != 200:
        logger.error("Unexpected Snitcher status %s", snitcher_resp.status_code)
        return None

    snitcher_data = snitcher_resp.json()
    logger.debug("Snitcher JSON: %s", snitcher_data)

    company_data = snitcher_data.get("company") or {}
    geo_data = snitcher_data.get("geoIP") or {}

    # -----------------------------
    # Geo fields from Snitcher
    # -----------------------------
    country = geo_data.get("country")
    country_code = geo_data.get("country_code")
    state = geo_data.get("state")
    city = geo_data.get("city")

    # -----------------------------
    # Additional enrichment fields
    # -----------------------------
    postal_code = geo_data.get("postal_code") or geo_data.get("zip")

    company_type = company_data.get("type")
    industry = company_data.get("industry")

    # Ensure list format for JSONFields
    categories = company_data.get("categories") or []
    keywords = company_data.get("keywords") or []
    technologies = company_data.get("technologies") or []

    # Defensive normalization (important)
    if not isinstance(categories, list):
        categories = [categories]

    if not isinstance(keywords, list):
        keywords = [keywords]

    if not isinstance(technologies, list):
        technologies = [technologies]

    company_name = (
        company_data.get("name")
        or company_data.get("domain")
        or snitcher_data.get("domain")
        or user_profile.company_name
    )

    domain = (
        company_data.get("website")
        or company_data.get("domain")
        or snitcher_data.get("domain")
        or root_url
    )

    employees = company_data.get("employee_range")
    revenue = company_data.get("annual_revenue")
    country_code = geo_data.get("country_code")

    # Enrich (logo)
    enrich_url = f"https://api.companyenrich.com/companies/enrich?domain={domain}"
    enrich_headers = {
        "accept": "application/json",
        "Authorization": "Bearer F0nyDGCBOfKKntUYWek9vO"
    }

    logger.info("Calling CompanyEnrich for domain %s", domain)

    try:
        enrich_resp = requests.get(enrich_url, headers=enrich_headers)

        enrich_data = enrich_resp.json()
        logger.debug("CompanyEnrich raw response: %s", enrich_data)

        logo_url = enrich_data.get("logo_url")

        # Optional enrichments (provider-dependent)
        technologies = enrich_data.get("technologies") or technologies
        categories = enrich_data.get("categories") or categories
        keywords = enrich_data.get("keywords") or keywords
        company_type = enrich_data.get("type") or company_type

        location = enrich_data.get("location") or {}

        postal_code = location.get("postal_code") or postal_code

        # Optional but more precise than IP-based geo
        country = (location.get("country") or {}).get("name") or country
        country_code = (location.get("country") or {}).get("code") or country_code
        state = (location.get("state") or {}).get("name") or state
        city = (location.get("city") or {}).get("name") or city

    except Exception:
        logger.exception("CompanyEnrich request failed")
        logo_url = None

    # Log lookup (deduplicated)
    ipinfo_obj, created = IpInfo.objects.get_or_create(
        ip_address=ip,
        defaults={
            "company_name": company_name,
            "domain": domain,
            "status": "Found",
            "click_id": click_id,
        }
    )
    if not created:
        # Update with enriched info if missing
        ipinfo_obj.company_name = company_name
        ipinfo_obj.domain = domain
        ipinfo_obj.status = "Found"
        ipinfo_obj.click_id = click_id
        ipinfo_obj.save()

    # Extract UTMs
    utm_source = query_params.get("utm_source", ["null"])[0]
    utm_medium = query_params.get("utm_medium", ["null"])[0]
    utm_content = query_params.get("utm_content", ["null"])[0]
    utm_id = query_params.get("utm_id", ["null"])[0]
    utm_term = query_params.get("utm_term", ["null"])[0]
    utm_campaign = query_params.get("utm_campaign", ["null"])[0]

    company = Company.objects.create(
        user=user,
        logo_url=logo_url,
        company_name=company_name,
        domain=domain,
        url_visited=url_visited,
        employees=employees,
        revenue=revenue,

        # NEW FIELDS
        postal_code=postal_code,
        company_type=company_type,
        industry=industry,
        categories=categories,
        keywords=keywords,
        technologies=technologies,
        country=country,
        state=state,
        city=city,

        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_content=utm_content,
        utm_id=utm_id,
        utm_term=utm_term,
        utm_campaign=utm_campaign,
        click_id=click_id,
        ad_type=ad_type,
        ip_address=ip,
        country_code=country_code,
    )
    print(company)

    logger.info("Company created with ID %s", company.id)

    return company


def create_company_visit(company, payload):
    logger.info("Creating visits for company %s", company.id)

    events = payload.get("events", [])

    if not events:
        logger.warning("Visit creation skipped, no events")
        return

    for ev in events:
        ts = parse_datetime(ev.get("created_at"))

        if not ts:
            logger.warning("Skipping event with invalid timestamp: %s", ev)
            continue

        CompanyVisit.objects.create(
            company=company,
            event_name=ev.get("event_name", "unknown_event"),
            timestamp=ts,
            user_agent=ev.get("context", {}).get("user_agent", ""),
            device_type=ev.get("context", {}).get("device", {}).get("type", ""),
            url_visited=(
                ev.get("context", {}).get("page", {}).get("url")
                or ev.get("event_properties", {}).get("$url", "")
            ),
            event_properties=ev.get("event_properties", {}),
        )

        logger.debug("Visit created: %s", ev)


def append_company_visit(company, payload):
    logger.info("Appending new visits to company %s", company.id)

    events = payload.get("events", [])
    if not events:
        logger.warning("Append skipped, no events present")
        return

    last_visit = (
        CompanyVisit.objects.filter(company=company)
        .order_by("-timestamp")
        .first()
    )

    last_timestamp = last_visit.timestamp if last_visit else None
    logger.debug("Last saved visit timestamp: %s", last_timestamp)

    new_visits = []

    for ev in events:
        ts_str = ev.get("created_at")
        ts = parse_datetime(ts_str)

        if not ts:
            logger.warning("Skipping event with invalid timestamp: %s", ev)
            continue

        if last_timestamp and ts <= last_timestamp:
            logger.debug("Skipping older event at %s", ts)
            continue

        new_visits.append(
            CompanyVisit(
                company=company,
                event_name=ev.get("event_name", "unknown_event"),
                timestamp=ts,
                user_agent=ev.get("context", {}).get("user_agent", ""),
                device_type=ev.get("context", {}).get("device", {}).get("type", ""),
                url_visited=(
                    ev.get("context", {}).get("page", {}).get("url")
                    or ev.get("event_properties", {}).get("$url", "")
                ),
                event_properties=ev.get("event_properties", {}),
            )
        )

        logger.debug("New visit queued: %s", ev)

    if new_visits:
        CompanyVisit.objects.bulk_create(new_visits)
        logger.info("Appended %s new visits", len(new_visits))
    else:
        logger.info("No new visits to append")

