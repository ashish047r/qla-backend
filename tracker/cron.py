from datetime import timedelta
import logging

from django.utils import timezone

from .models import Company

logger = logging.getLogger(__name__)


def update_conversion_status():
    """
    Update stale conversion statuses:
    - Processing -> Not Sent after 24 hours.
    - Not Sent -> Expired after 90 days.
    """
    now = timezone.now()

    processing_cutoff = now - timedelta(hours=24)
    processing_qs = Company.objects.filter(
        conversion_status="Processing",
        timestamp__lte=processing_cutoff,
    )
    processing_updated = processing_qs.update(conversion_status="Not Sent")
    logger.info("Converted %s Processing visits to Not Sent (cutoff=%s)", processing_updated, processing_cutoff)

    expiry_cutoff = now - timedelta(days=90)
    expiry_qs = Company.objects.filter(
        conversion_status="Not Sent",
        timestamp__lte=expiry_cutoff,
    )
    expired_updated = expiry_qs.update(conversion_status="Expired")
    logger.info("Converted %s Not Sent visits to Expired (cutoff=%s)", expired_updated, expiry_cutoff)

    return (
        f"Marked {processing_updated} Processing visits as Not Sent; "
        f"marked {expired_updated} Not Sent visits as Expired."
    )
