# notifications/serializers.py
from rest_framework import serializers
from .models import DeviceToken, Notification, SystemMaintenance
from rest_framework.exceptions import ValidationError


# class DeviceTokenSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = DeviceToken
#         fields = ['id', 'token', 'device_type', 'is_active']
#         read_only_fields = ['id', 'created_at', 'updated_at']
    
#     def create(self, validated_data):
#         # Set the user from the request context
#         user = self.context['request'].user
#         validated_data['user'] = user
        
#         # Check if token already exists for user, update instead of creating new
#         try:
#             device_token = DeviceToken.objects.get(
#                 user=user, 
#                 token=validated_data['token']
#             )
#             # Update existing token
#             for key, value in validated_data.items():
#                 setattr(device_token, key, value)
#             device_token.save()
#             return device_token
#         except DeviceToken.DoesNotExist:
#             # Create new token
#             return super().create(validated_data)


class DeviceTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceToken
        fields = ['id', 'token', 'device_type', 'is_active']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def create(self, validated_data):
        user = self.context['request'].user
        token = validated_data.get('token')
        print(user,token)
        
        try:
            # Check if token already exists in the database
            device_token = DeviceToken.objects.get(token=token)
            
            # If the token exists but for a different user, update the user
            if device_token.user != user:
                device_token.user = user
                for key, value in validated_data.items():
                    setattr(device_token, key, value)
                device_token.save()
                return device_token
            else:
                # If it's the same user, just update other fields
                for key, value in validated_data.items():
                    setattr(device_token, key, value)
                device_token.save()
                return device_token
                
        except DeviceToken.DoesNotExist:
            # Create a new token if none exists
            validated_data['user'] = user
            return super().create(validated_data)

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'title', 'message', 'notification_type', 
                  'is_read', 'data', 'created_at']
        read_only_fields = ['id', 'created_at']
    
    def to_representation(self, instance):
        data = super().to_representation(instance)
        
        # Parse the JSON data if it exists
        if instance.data:
            data['data'] = instance.data
            
        return data


class AdminNotificationSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = Notification
        fields = ['id', 'user_id', 'title', 'message', 'notification_type', 'data']
    
    def create(self, validated_data):
        user_id = validated_data.pop('user_id')
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        try:
            user = User.objects.get(id=user_id)
            validated_data['user'] = user
            return super().create(validated_data)
        except User.DoesNotExist:
            raise serializers.ValidationError({"user_id": "User does not exist"})


class SystemMaintenanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemMaintenance
        fields = ['id', 'title', 'message', 'is_active', 'start_time', 'end_time', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']