# notifications/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone
from auditlog.registry import auditlog
from auditlog.models import AuditlogHistoryField


class DeviceToken(models.Model):
    """Store user device tokens for push notifications"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='device_tokens')
    token = models.CharField(max_length=255)
    device_type = models.CharField(max_length=20, choices=[
        ('ANDROID', 'Android'),
        ('IOS', 'iOS'),
    ])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = AuditlogHistoryField()

    class Meta:
        unique_together = ('user', 'token')

    def __str__(self):
        return f"{self.user.email} - {self.device_type} Device"

class Notification(models.Model):
    """Store notifications sent to users"""
    NOTIFICATION_TYPE_CHOICES = [
        ('SUBSCRIPTION_EXPIRY', 'Subscription Expiry'),
        ('NEW_SUBSCRIPTION', 'New Subscription'),
        ('ADMIN_MESSAGE', 'Admin Message'),
        ('SYSTEM_MAINTENANCE', 'System Maintenance'),
        ('PAYMENT_SUCCESS', 'Payment Success'),
        ('PAYMENT_FAILED', 'Payment Failed'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications', null=True, blank=True)
    title = models.CharField(max_length=255)
    message = models.TextField()
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPE_CHOICES)
    is_read = models.BooleanField(default=False)
    data = models.JSONField(null=True, blank=True)  # For additional data to be sent with notification
    created_at = models.DateTimeField(auto_now_add=True)
    history = AuditlogHistoryField()

    def __str__(self):
        if self.user:
            return f"{self.notification_type} for {self.user.email}"
        return f"{self.notification_type} - {self.title}"

class SystemMaintenance(models.Model):
    """Track system maintenance status"""
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_active = models.BooleanField(default=False)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = AuditlogHistoryField()

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"Maintenance: {self.title} ({status})"

# Register models with auditlog
auditlog.register(DeviceToken)
auditlog.register(Notification)
auditlog.register(SystemMaintenance)