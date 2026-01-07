from django.db import models
from django.contrib.auth.models import User
 
# Create your models here.
class GoogleAdsProject(models.Model): 
    user = models.ForeignKey(User, on_delete=models.CASCADE, default=None, null=True, blank=True)
    refresh_token = models.CharField(max_length=500)                  
    customer_id = models.CharField(max_length=500)
    customer_name = models.CharField(max_length=500, blank=True)
    conversion_action_resource_name = models.CharField(max_length=500, blank=True)
    conversion_action_descriptive_name = models.CharField(max_length=500, blank=True)
    conversion_action_category_name = models.CharField(max_length=50, blank=True)
    manager_id = models.IntegerField(default=0)
    def __str__(self):  
        return self.customer_name
