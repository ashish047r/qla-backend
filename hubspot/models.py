# hubspot/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

User = get_user_model()

class HubspotProject(models.Model):
    # If your app is multi-tenant you can use account_id/hubspot_portal_id; else link to a user
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    hubspot_account_id = models.CharField(max_length=255, blank=True, null=True)
    hubspot_account_name = models.CharField(max_length=255, null=True, blank=True)
    hubspot_user_name = models.CharField(max_length=255, null=True, blank=True)
    access_token = models.TextField()
    refresh_token = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.hubspot_account_name} ({self.hubspot_account_id})"
