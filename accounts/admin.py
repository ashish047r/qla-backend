from django.contrib import admin
from .models import UserProfile


class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'pixel_id', 'company_name')  # Show username and pixel_id in admin list
    

admin.site.register(UserProfile, UserProfileAdmin)
