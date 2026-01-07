import json
import requests
from django.utils import timezone
from datetime import timezone as dt_timezone

from tracker.models import Company, CompanyVisit
from facebook_ads.utils import sha256_hash, normalize_str, format_fbc


def send_conversion_events(user, fb_project, conversions):
    dataset_id = fb_project.meta_pixel_id
    access_token = fb_project.meta_pixel_access_token

    url = f"https://graph.facebook.com/v24.0/{dataset_id}/events"
    results = []

    for event in conversions:
        click_id = event.get("click_id")
        if not click_id:
            results.append({"input": event, "error": "click_id missing"})
            continue

        company = Company.objects.filter(user=user, click_id=click_id).order_by("timestamp").first()
        if not company:
            results.append({"input": event, "error": "Company not found"})
            continue

        visit = CompanyVisit.objects.filter(company=company).order_by("timestamp").first()
        if not visit:
            results.append({"input": event, "error": "CompanyVisit not found"})
            continue

        visit_ts = visit.timestamp
        if timezone.is_naive(visit_ts):
            visit_ts = timezone.make_aware(visit_ts, dt_timezone.utc)
        else:
            visit_ts = visit_ts.astimezone(dt_timezone.utc)

        fbc = format_fbc(click_id, company.domain, company.timestamp or visit_ts)

        data = [
            {
                "event_name": "GS ICP Company Visit",
                "event_time": int(visit_ts.timestamp()),
                "user_data": {
                    "client_ip_address": company.ip_address,
                    "client_user_agent": visit.user_agent,
                    "fbc": fbc,
                    "external_id": sha256_hash(str(user.id)),
                    "st": sha256_hash((normalize_str(company.state) or "").lower()),
                    "ct": sha256_hash((normalize_str(company.city) or "").lower()),
                    "zp": sha256_hash((normalize_str(company.postal_code) or "").lower()),
                },
                "action_source": "website",
            }
        ]

        response = requests.post(
            url,
            files={
                "data": (None, json.dumps(data)),
                "access_token": (None, access_token),
            },
            timeout=10,
        )

        try:
            resp_json = response.json()
        except Exception:
            resp_json = {"raw": response.text}

        results.append({
            "input": event,
            "status_code": response.status_code,
            "response": resp_json
        })

    return results
