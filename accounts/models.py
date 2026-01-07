import secrets
import uuid

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    # Allow NULL so multiple profiles can share "no pixel" without violating uniqueness.
    pixel_id = models.CharField(max_length=255, editable=True, blank=True)
    company_name = models.CharField(max_length=255)
    # Yes, company_domains is a JSONField with default as list, which acts as a list field for storing up to 5 company domains.
    company_domains = models.JSONField(default=list, blank=True, help_text="List of up to 5 company domains as URLs")


    def __str__(self):
        return self.user.username

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.userprofile.save()
