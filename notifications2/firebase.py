# notifications/firebase.py
import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings
import os
import json

# Initialize Firebase Admin SDK
def initialize_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred)

# Function to send push notification
def send_push_notification(token, title, message, data=None):
    """
    Send push notification to a device token
    
    Args:
        token (str): FCM device token
        title (str): Notification title
        message (str): Notification message
        data (dict): Additional data to send with notification
    """
    initialize_firebase()
    
    # Set notification content
    notification = messaging.Notification(
        title=title,
        body=message
    )
    
    # Create message
    message = messaging.Message(
        notification=notification,
        data=data or {},
        token=token
    )
    
    try:
        # Send message
        response = messaging.send(message)
        return True, response
    except Exception as e:
        print(f"Error sending notification: {e}")
        return False, str(e)

# Function to send notification to multiple devices
def send_bulk_notifications(tokens, title, message, data=None):
    """
    Send push notifications to multiple device tokens
    
    Args:
        tokens (list): List of FCM device tokens
        title (str): Notification title
        message (str): Notification message
        data (dict): Additional data to send with notification
    """
    initialize_firebase()
    
    if not tokens:
        return False, "No tokens provided"
    
    # Create a MulticastMessage
    multicast_message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=title,
            body=message
        ),
        data=data or {},
        tokens=tokens,
    )
    
    try:
        # Send message
        response = messaging.send_multicast(multicast_message)
        return True, f"Successfully sent {response.success_count} messages, failed: {response.failure_count}"
    except Exception as e:
        print(f"Error sending notifications: {e}")
        return False, str(e)