# notifications/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DeviceTokenViewSet,
    NotificationViewSet,
    AdminNotificationViewSet,
    SystemMaintenanceViewSet,
    TestPushNotificationView
)

router = DefaultRouter()
router.register(r'device-tokens', DeviceTokenViewSet, basename='device-tokens')
router.register(r'notifications', NotificationViewSet, basename='notifications')
router.register(r'admin-notifications', AdminNotificationViewSet, basename='admin-notifications')
router.register(r'system-maintenance', SystemMaintenanceViewSet, basename='system-maintenance')

urlpatterns = [
    path('', include(router.urls)),
    path('test-push/', TestPushNotificationView.as_view(), name='test-push'),
]


# Add this to your main urls.py
# from django.urls import path, include
# 
# urlpatterns = [
#     ...
#     path('api/notifications/', include('notifications.urls')),
#     ...
# ]