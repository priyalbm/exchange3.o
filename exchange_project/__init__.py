default_app_config = 'notifications2.apps.Notifications2Config'

from django.apps import AppConfig

class NotificationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'notifications2'

    def ready(self):
        import notifications2.signals
        
        # Initialize Firebase when the app is ready
        try:
            from .firebase import initialize_firebase
            initialize_firebase()
        except Exception as e:
            # Log the error but don't crash the app
            print(f"Error initializing Firebase: {e}")