from django.core.management.base import BaseCommand
from notifications2.firebase import send_push_notification

class Command(BaseCommand):
    help = 'Test Firebase Cloud Messaging configuration'

    def add_arguments(self, parser):
        parser.add_argument('--token', type=str, required=True, help='FCM device token to send test message to')

    def handle(self, *args, **options):
        token = options['token']
        
        self.stdout.write(self.style.SUCCESS('Testing Firebase Cloud Messaging...'))
        
        success, response = send_push_notification(
            token=token,
            title="Test Notification",
            message="This is a test notification from Django",
            data={"test": "true"}
        )
        
        if success:
            self.stdout.write(self.style.SUCCESS(f'Successfully sent notification: {response}'))
        else:
            self.stdout.write(self.style.ERROR(f'Failed to send notification: {response}'))