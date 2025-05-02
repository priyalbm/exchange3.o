# notifications/views.py
from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Q
from .models import DeviceToken, Notification, SystemMaintenance
from .serializers import (
    DeviceTokenSerializer, 
    NotificationSerializer, 
    AdminNotificationSerializer,
    SystemMaintenanceSerializer
)
from .firebase import send_push_notification, send_bulk_notifications
from rest_framework.views import APIView


class DeviceTokenViewSet(viewsets.ModelViewSet):
    serializer_class = DeviceTokenSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return DeviceToken.objects.filter(user=self.request.user)
    
    @action(detail=False, methods=['delete'])
    def delete_token(self, request):
        token = request.data.get('token')
        if not token:
            return Response(
                {"error": "Token is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            device_token = DeviceToken.objects.get(
                user=request.user, 
                token=token
            )
            device_token.delete()
            return Response(
                {"message": "Token deleted successfully"}, 
                status=status.HTTP_200_OK
            )
        except DeviceToken.DoesNotExist:
            return Response(
                {"error": "Token not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        # Get user's notifications and system-wide notifications
        return Notification.objects.filter(
            Q(user=self.request.user) | 
            Q(notification_type='SYSTEM_MAINTENANCE', user=None)
        ).order_by('-created_at')
    
    @action(detail=True, methods=['patch'])
    def mark_as_read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save()
        return Response(
            {"message": "Notification marked as read"}, 
            status=status.HTTP_200_OK
        )
    
    @action(detail=False, methods=['patch'])
    def mark_all_as_read(self, request):
        notifications = self.get_queryset()
        notifications.update(is_read=True)
        return Response(
            {"message": "All notifications marked as read"}, 
            status=status.HTTP_200_OK
        )


class AdminNotificationViewSet(viewsets.ModelViewSet):
    serializer_class = AdminNotificationSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset = Notification.objects.all()
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Create notification
        notification = serializer.save()
        
        # Send push notification to user
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.get(id=request.data.get('user_id'))
        
        # Get all user's device tokens
        device_tokens = DeviceToken.objects.filter(user=user, is_active=True)
        tokens = [dt.token for dt in device_tokens]
        
        # Prepare data payload
        data = notification.data if notification.data else {}
        data_payload = {
            'notification_id': str(notification.id),
            'notification_type': notification.notification_type,
            **data
        }
        
        # Send notification to all user devices
        if tokens:
            success, message = send_bulk_notifications(
                tokens, 
                notification.title, 
                notification.message,
                data=data_payload
            )
            
            if not success:
                # We still created the notification in database, so don't return an error
                # Just log the issue with sending push notification
                print(f"Error sending push notification: {message}")
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class SystemMaintenanceViewSet(viewsets.ModelViewSet):
    serializer_class = SystemMaintenanceSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset = SystemMaintenance.objects.all().order_by('-created_at')
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        maintenance = serializer.save()
        
        # If maintenance is active, create a system notification and send push
        if maintenance.is_active:
            # Create notification record
            notification = Notification.objects.create(
                title=maintenance.title,
                message=maintenance.message,
                notification_type='SYSTEM_MAINTENANCE',
                user=None,  # System-wide notification
                data={
                    'start_time': maintenance.start_time.isoformat(),
                    'end_time': maintenance.end_time.isoformat(),
                    'maintenance_id': maintenance.id
                }
            )
            
            # Get all active device tokens
            all_tokens = DeviceToken.objects.filter(is_active=True)
            tokens = [dt.token for dt in all_tokens]
            
            # Prepare data payload
            data_payload = {
                'notification_id': str(notification.id),
                'notification_type': 'SYSTEM_MAINTENANCE',
                'maintenance_id': str(maintenance.id),
            }
            
            # Send notification to all user devices
            if tokens:
                send_bulk_notifications(
                    tokens, 
                    maintenance.title, 
                    maintenance.message,
                    data=data_payload
                )
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        old_is_active = instance.is_active
        
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        maintenance = serializer.save()
        
        # If maintenance switched from inactive to active
        if not old_is_active and maintenance.is_active:
            # Create notification record
            notification = Notification.objects.create(
                title=maintenance.title,
                message=maintenance.message,
                notification_type='SYSTEM_MAINTENANCE',
                user=None,  # System-wide notification
                data={
                    'start_time': maintenance.start_time.isoformat(),
                    'end_time': maintenance.end_time.isoformat(),
                    'maintenance_id': maintenance.id
                }
            )
            
            # Get all active device tokens
            all_tokens = DeviceToken.objects.filter(is_active=True)
            tokens = [dt.token for dt in all_tokens]
            
            # Prepare data payload
            data_payload = {
                'notification_id': str(notification.id),
                'notification_type': 'SYSTEM_MAINTENANCE',
                'maintenance_id': str(maintenance.id),
            }
            
            # Send notification to all user devices
            if tokens:
                send_bulk_notifications(
                    tokens, 
                    maintenance.title, 
                    maintenance.message,
                    data=data_payload
                )
        
        return Response(serializer.data)


class TestPushNotificationView(APIView):
    """Test API to send a test push notification to a device token"""
    permission_classes = [permissions.IsAdminUser]
    
    def post(self, request):
        token = request.data.get('token')
        title = request.data.get('title', 'Test Notification')
        message = request.data.get('message', 'This is a test notification')
        data = request.data.get('data', {})
        
        if not token:
            return Response(
                {"error": "Token is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        success, response = send_push_notification(token, title, message, data)
        
        if success:
            return Response(
                {"message": "Notification sent successfully"}, 
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"error": f"Failed to send notification: {response}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )