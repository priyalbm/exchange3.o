# notifications/tasks.py
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from subscriptions.models import Subscription
from .services import send_subscription_expiry_notification


@shared_task
def check_expiring_subscriptions():
    """
    Check for subscriptions that will expire in the next 3 days
    and send notifications to users
    """
    now = timezone.now()
    expiry_date_max = now + timedelta(days=3)
    expiry_date_min = now + timedelta(days=1)
    
    # Find active subscriptions expiring within 3 days
    expiring_subscriptions = Subscription.objects.filter(
        status='ACTIVE', 
        end_date__gte=expiry_date_min, 
        end_date__lte=expiry_date_max
    )
    
    for subscription in expiring_subscriptions:
        send_subscription_expiry_notification(subscription)
    
    return f"Processed {expiring_subscriptions.count()} expiring subscriptions"


@shared_task
def check_expired_subscriptions():
    """
    Check for subscriptions that have expired but are still marked as active
    and update their status
    """
    now = timezone.now()
    
    # Find active subscriptions that have expired
    expired_subscriptions = Subscription.objects.filter(
        status='ACTIVE',
        end_date__lt=now
    )
    
    # Update status to EXPIRED
    count = expired_subscriptions.count()
    expired_subscriptions.update(status='EXPIRED')
    
    return f"Updated {count} expired subscriptions"