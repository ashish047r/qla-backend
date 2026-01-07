from django.db import models
from django.contrib.auth.models import User

import datetime
from django.utils import timezone



class Company(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    logo_url = models.URLField(null=True, blank=True)
    company_name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255)

    employees = models.CharField(max_length=255, null=True, blank=True)
    revenue = models.CharField(max_length=255, null=True, blank=True)
    ip_address = models.CharField(max_length=255, null=True, blank=True)

    # -----------------------------
    # New company enrichment fields
    # -----------------------------
    postal_code = models.CharField(max_length=20, null=True, blank=True)
    company_type = models.CharField(max_length=100, null=True, blank=True)
    industry = models.CharField(max_length=255, null=True, blank=True)

    categories = models.JSONField(default=list, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    technologies = models.JSONField(default=list, blank=True)

    country = models.CharField(max_length=100, null=True, blank=True)
    state = models.CharField(max_length=100, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)

    # -----------------------------
    # Conversion tracking
    # -----------------------------
    CONVERSION_STATUS_CHOICES = [
        ("Sent", "Sent"),
        ("Not Sent", "Not Sent"),
        ("Expired", "Expired"),
        ("Processing", "Processing"),
    ]

    conversion_status = models.CharField(
        max_length=20,
        choices=CONVERSION_STATUS_CHOICES,
        default="Processing",
    )

    url_visited = models.URLField(max_length=800)
    timestamp = models.DateTimeField(auto_now_add=True)

    utm_source = models.CharField(max_length=255, null=True, blank=True)
    utm_medium = models.CharField(max_length=255, null=True, blank=True)
    utm_content = models.CharField(max_length=255, null=True, blank=True)
    utm_id = models.CharField(max_length=255, null=True, blank=True)
    utm_term = models.CharField(max_length=255, null=True, blank=True)
    utm_campaign = models.CharField(max_length=255, null=True, blank=True)

    click_id = models.CharField(max_length=255, null=True, blank=True)
    ad_type = models.CharField(max_length=255, null=True, blank=True)
    country_code = models.CharField(max_length=10, null=True, blank=True)

    def __str__(self):
        return f"{self.company_name} ({self.domain}) visited {self.url_visited} at {self.timestamp}"






class CompanyVisit(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    event_name = models.CharField(max_length=100)
    timestamp = models.DateTimeField()
    user_agent = models.CharField(max_length=255)
    device_type = models.CharField(max_length=255)
    url_visited = models.URLField(max_length=800)
    event_properties = models.JSONField()

    

    def __str__(self):
        return f"{self.company} visited {self.url_visited} at {self.timestamp}"





class IpInfo(models.Model):
    ip_address = models.CharField(max_length=255)
    company_name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=255, default="Found")
    click_id = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"{self.ip_address} ({self.company_name}) ({self.domain}) at {self.timestamp}"

# curl --get 'https://graph.facebook.com/v18.0/ads_archive' 
#   -d 'access_token=YOUR_ACCESS_TOKEN' 
#   -d 'ad_active_status=ALL' 
#   -d 'fields=ad_creative_body,ad_creative_link_caption,ad_creative_link_description,ad_creative_link_title,ad_delivery_start_time,ad_delivery_stop_time,bylines,call_to_action_types,demographic_distribution,funding_entity,page_id,page_name,spend,impressions' 
#   -d 'search_terms=YOUR_COMPANY_NAME'


# verify pixel me bhi send list of domains