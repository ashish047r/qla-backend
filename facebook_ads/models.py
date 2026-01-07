from django.db import models
from django.contrib.auth.models import User
 
# Create your models here.
class FacebookAdsProject(models.Model): 
    user = models.ForeignKey(User, on_delete=models.CASCADE, default=None, null=True, blank=True)
    access_token = models.CharField(max_length=500)                  
    customer_id = models.CharField(max_length=500)
    customer_name = models.CharField(max_length=500, blank=True)


    meta_pixel_id = models.CharField(max_length=500, blank=True)
    meta_pixel_access_token = models.CharField(max_length=500, blank=True)



    def __str__(self):  
        return self.customer_name
