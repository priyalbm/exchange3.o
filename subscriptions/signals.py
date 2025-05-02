from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Subscription
from notifications2.models import Notification
from django.utils.timezone import now

@receiver(post_save, sender=Subscription)
def notify_plan_expiry(sender, instance, created, **kwargs):
    settings = NotificationSetting.get_settings()
    if not created and instance.status == 'EXPIRED' and settings.expiry_notification:
        Notification.objects.create(
            user=instance.user,
            title="Plan Expired",
            message=f"Your subscription to {instance.plan.name} has expired."
        )
