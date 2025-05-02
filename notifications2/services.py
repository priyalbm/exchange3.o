# notifications/services.py
from django.utils import timezone
from .models import Notification, DeviceToken
from .firebase import send_bulk_notifications
import json


def send_subscription_expiry_notification(subscription):
    """
    Send notification when a subscription is about to expire
    
    Args:
        subscription: Subscription object
    """
    # Create notification record
    notification = Notification.objects.create(
        user=subscription.user,
        title="Subscription Expiry",
        message=f"Your {subscription.plan.name} subscription will expire on {subscription.end_date.strftime('%d %b %Y')}.",
        notification_type="SUBSCRIPTION_EXPIRY",
        data={
            'subscription_id': subscription.id,
            'plan_name': subscription.plan.name,
            'expiry_date': subscription.end_date.isoformat()
        }
    )
    
    # Get user's device tokens
    device_tokens = DeviceToken.objects.filter(user=subscription.user, is_active=True)
    tokens = [dt.token for dt in device_tokens]
    
    # Prepare data payload
    data_payload = {
        'notification_id': str(notification.id),
        'notification_type': 'SUBSCRIPTION_EXPIRY',
        'subscription_id': str(subscription.id),
        'plan_name': subscription.plan.name,
        'expiry_date': subscription.end_date.isoformat()
    }
    
    # Send notification to all user devices
    if tokens:
        success, message = send_bulk_notifications(
            tokens, 
            notification.title, 
            notification.message,
            data=data_payload
        )
        return success, message
    
    return False, "No device tokens found"


def send_new_subscription_notification(subscription):
    """
    Send notification when a new subscription is activated
    
    Args:
        subscription: Subscription object
    """
    # Create notification record
    notification = Notification.objects.create(
        user=subscription.user,
        title="Subscription Activated",
        message=f"Your {subscription.plan.name} subscription has been activated. Valid until {subscription.end_date.strftime('%d %b %Y')}.",
        notification_type="NEW_SUBSCRIPTION",
        data={
            'subscription_id': subscription.id,
            'plan_name': subscription.plan.name,
            'start_date': subscription.start_date.isoformat(),
            'end_date': subscription.end_date.isoformat()
        }
    )
    
    # Get user's device tokens
    device_tokens = DeviceToken.objects.filter(user=subscription.user, is_active=True)
    tokens = [dt.token for dt in device_tokens]
    
    # Prepare data payload
    data_payload = {
        'notification_id': str(notification.id),
        'notification_type': 'NEW_SUBSCRIPTION',
        'subscription_id': str(subscription.id),
        'plan_name': subscription.plan.name,
        'start_date': subscription.start_date.isoformat(),
        'end_date': subscription.end_date.isoformat()
    }
    
    # Send notification to all user devices
    if tokens:
        success, message = send_bulk_notifications(
            tokens, 
            notification.title, 
            notification.message,
            data=data_payload
        )
        return success, message
    
    return False, "No device tokens found"


def send_payment_success_notification(payment):
    """
    Send notification when a payment is successful
    
    Args:
        payment: PaymentTransaction object
    """
    # Create notification record
    notification = Notification.objects.create(
        user=payment.subscription.user,
        title="Payment Successful",
        message=f"Your payment of {payment.currency} {payment.amount} for {payment.subscription.plan.name} subscription was successful.",
        notification_type="PAYMENT_SUCCESS",
        data={
            'transaction_id': payment.id,
            'subscription_id': payment.subscription.id,
            'amount': str(payment.amount),
            'currency': payment.currency,
            'plan_name': payment.subscription.plan.name
        }
    )
    
    # Get user's device tokens
    device_tokens = DeviceToken.objects.filter(user=payment.subscription.user, is_active=True)
    tokens = [dt.token for dt in device_tokens]
    
    # Prepare data payload
    data_payload = {
        'notification_id': str(notification.id),
        'notification_type': 'PAYMENT_SUCCESS',
        'transaction_id': str(payment.id),
        'subscription_id': str(payment.subscription.id),
        'amount': str(payment.amount),
        'currency': payment.currency
    }
    
    # Send notification to all user devices
    if tokens:
        success, message = send_bulk_notifications(
            tokens, 
            notification.title, 
            notification.message,
            data=data_payload
        )
        return success, message
    
    return False, "No device tokens found"


def send_payment_failed_notification(payment):
    """
    Send notification when a payment fails
    
    Args:
        payment: PaymentTransaction object
    """
    # Create notification record
    notification = Notification.objects.create(
        user=payment.subscription.user,
        title="Payment Failed",
        message=f"Your payment of {payment.currency} {payment.amount} for {payment.subscription.plan.name} subscription failed. Please try again.",
        notification_type="PAYMENT_FAILED",
        data={
            'transaction_id': payment.id,
            'subscription_id': payment.subscription.id,
            'amount': str(payment.amount),
            'currency': payment.currency,
            'plan_name': payment.subscription.plan.name
        }
    )
    
    # Get user's device tokens
    device_tokens = DeviceToken.objects.filter(user=payment.subscription.user, is_active=True)
    tokens = [dt.token for dt in device_tokens]
    
    # Prepare data payload
    data_payload = {
        'notification_id': str(notification.id),
        'notification_type': 'PAYMENT_FAILED',
        'transaction_id': str(payment.id),
        'subscription_id': str(payment.subscription.id),
        'amount': str(payment.amount),
        'currency': payment.currency
    }
    
    # Send notification to all user devices
    if tokens:
        success, message = send_bulk_notifications(
            tokens, 
            notification.title, 
            notification.message,
            data=data_payload
        )
        return success, message
    
    return False, "No device tokens found"