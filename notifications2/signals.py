# notifications/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.conf import settings

from subscriptions.models import Subscription, PaymentTransaction
from .services import (
    send_subscription_expiry_notification,
    send_new_subscription_notification,
    send_payment_success_notification,
    send_payment_failed_notification
)


@receiver(post_save, sender=Subscription)
def subscription_post_save(sender, instance, created, **kwargs):
    """Handle subscription events"""
    # Send notification when subscription status changes to ACTIVE
    if instance.status == 'ACTIVE' and instance.payment_status == 'SUCCESS':
        # For new subscriptions or when status just changed to ACTIVE
        send_new_subscription_notification(instance)
    
    # Check if subscription is about to expire (within 3 days)
    if instance.status == 'ACTIVE' and instance.end_date:
        days_until_expiry = (instance.end_date - timezone.now()).days
        if days_until_expiry <= 3 and days_until_expiry >= 0:
            # Send expiry notification
            send_subscription_expiry_notification(instance)


@receiver(post_save, sender=PaymentTransaction)
def payment_transaction_post_save(sender, instance, created, **kwargs):
    """Handle payment transaction events"""
    if created or instance.tracker.has_changed('status'):
        if instance.status == 'SUCCESS':
            # Payment successful
            send_payment_success_notification(instance)
        elif instance.status == 'FAILED':
            # Payment failed
            send_payment_failed_notification(instance)