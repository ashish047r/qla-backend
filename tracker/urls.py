from django.urls import path
from .views import VerifyPixelView, SendVisitDataView, GetVisitDataView, VisitToGoogleAdsConversionView, SetGoogleConversionEventView , VisitToFacebookAdsConversionView, SetFacebookConversionEventView, GetCompanyVisitDataView, ConversionStatusCronView, GetPixelData, ListRadarPixel, RadarWebhookConfig, DeactivateRadarTracking, ActivateRadarTracking, FindCompanyByIP, TestWebhookView,CreateCompanyView


urlpatterns = [
    path('verify_pixel/', VerifyPixelView.as_view(), name='verify_pixel'),
    path('send_visit_data/', SendVisitDataView.as_view(), name='send_visit_data'),
    path('get_visit_data/', GetVisitDataView.as_view(), name='get_visit_data'),
    path('visit_to_google_ads_conversion/', VisitToGoogleAdsConversionView.as_view(), name='visit_to_google_ads_conversion'),
    path('visit_to_facebook_ads_conversion/', VisitToFacebookAdsConversionView.as_view(), name='visit_to_facebook_ads_conversion'),

    path('set_google_conversion_event/', SetGoogleConversionEventView.as_view(), name='set_google_conversion_event'),
    path('set_facebook_conversion_event/', SetFacebookConversionEventView.as_view(), name='set_facebook_conversion_event'),

    path('get_company_visit_data/', GetCompanyVisitDataView.as_view(), name='get_company_visit_data_view'),
    path("run-cron/", ConversionStatusCronView.as_view()),

    path('webhook/',  GetPixelData.as_view(), name="my-webhook"),

    path('list-pixel/', ListRadarPixel.as_view(), name='list_radar_pixel'),
    path('webhook-config/', RadarWebhookConfig.as_view(), name='radar_webhook_config' ),
    path('deactivate_pixel/', DeactivateRadarTracking.as_view(), name='deactivate_radar_pixel'),
    path('activate_pixel/', ActivateRadarTracking.as_view(), name='activate_radar_pixel'),

    path('companyip/', FindCompanyByIP.as_view(), name='find-my-ip' ),

    path('test-webhook/', TestWebhookView.as_view(), name='test_webhook' ),




    path('create-company/', CreateCompanyView.as_view(), name='create_company')







]
