import hashlib
from urllib.parse import urlparse
from django.utils import timezone
from datetime import timezone as dt_timezone


def sha256_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_str(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def format_fbc(click_id, domain, observed_time):
    hostname = ""
    try:
        parsed = urlparse(domain)
        hostname = parsed.hostname or ""
    except Exception:
        hostname = domain or ""

    parts = [p for p in hostname.split(".") if p]
    subdomain_index = max(len(parts) - 1, 0)

    if timezone.is_naive(observed_time):
        observed_time = timezone.make_aware(observed_time, dt_timezone.utc)
    else:
        observed_time = observed_time.astimezone(dt_timezone.utc)

    creation_time_ms = int(observed_time.timestamp() * 1000)
    return f"fb.{subdomain_index}.{creation_time_ms}.{click_id}"
