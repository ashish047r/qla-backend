from django.contrib import admin
from .models import Company, IpInfo, CompanyVisit
# Register your models here.

class CompanyAdmin(admin.ModelAdmin):
    list_filter = ['ad_type', 'company_name', 'timestamp', 'domain']
    search_fields = ['company_name', 'domain', 'url_visited', 'ip_address']
    list_display = ['company_name', 'domain', 'url_visited', 'ad_type', 'timestamp', 'ip_address']
    readonly_fields = ['timestamp']

admin.site.register(Company, CompanyAdmin)


class CompanyVisitAdmin(admin.ModelAdmin):
    list_filter = ['event_name', 'device_type', 'timestamp']
    search_fields = [
        'company__company_name',
        'company__domain',
        'company__ip_address',
        'url_visited',
        'user_agent',
    ]
    list_display = ['company', 'event_name', 'url_visited', 'user_agent', 'device_type', 'event_properties']
    readonly_fields = ['timestamp']

admin.site.register(CompanyVisit, CompanyVisitAdmin)

class IpInfoAdmin(admin.ModelAdmin):
    list_filter = ['ip_address', 'company_name', 'domain', 'status']
    search_fields = ['ip_address', 'company_name', 'domain']
    list_display = ['ip_address', 'company_name', 'domain', 'status']

admin.site.register(IpInfo, IpInfoAdmin)
