import logging
import requests
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile
from pixel_tracker.settings import SNITCHER_RADAR_API_KEY, SNITCHER_TRACKER_API_URL

logger = logging.getLogger(__name__)


@receiver(post_save, sender=UserProfile)
def generate_profile_pixel(sender, instance: UserProfile, created: bool, **kwargs):
    # Only act on creation; updates are already covered.
    if not created:
        return

    if instance.pixel_id:
        # Pixel already set; avoid duplicate API calls.
        return

    user_profile_pk = instance.pk
    username = instance.user.username
    print("Generating pixel for user profile:", username)

    def _assign_pixel():
        url = SNITCHER_TRACKER_API_URL
        headers = {
            "Authorization": "Bearer " + SNITCHER_RADAR_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {"internal_identifier": username}

        try:
            res = requests.post(url, json=payload, headers=headers, timeout=10)
            if res.status_code >= 400:
                logger.error(
                    "Snitcher API error for profile %s (status %s): %s",
                    user_profile_pk,
                    res.status_code,
                    res.text,
                )
                return
        except requests.RequestException:
            logger.exception("Snitcher API call failed for profile %s", user_profile_pk)
            return

        data = res.json().get("data")
        if not data:
            logger.error("No data returned from Snitcher for profile %s", user_profile_pk)
            return

        if isinstance(data, list):
            item = data[0] if data else None
        elif isinstance(data, dict):
            item = data
        else:
            logger.error("Unexpected Snitcher response format for profile %s: %r", user_profile_pk, data)
            return

        if not item:
            logger.error("Empty data item from Snitcher for profile %s", user_profile_pk)
            return

        tracking_script_id = item.get("tracking_script_id")
        if not tracking_script_id:
            logger.error("No tracking_script_id in Snitcher response for profile %s", user_profile_pk)
            return

        # Use update() to avoid triggering the signal again.
        UserProfile.objects.filter(pk=user_profile_pk).update(pixel_id=tracking_script_id)

    # Run after the transaction commits so we don't hold DB locks during the API call.
    transaction.on_commit(_assign_pixel)
