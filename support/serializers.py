from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Ticket, Message, TicketHistory

class UserSerializer(serializers.ModelSerializer):
    is_admin = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_admin']
        
    def get_is_admin(self, obj):
        return obj.is_staff or obj.is_superuser

# class MessageSerializer(serializers.ModelSerializer):
#     sender_name = serializers.SerializerMethodField()
    
#     class Meta:
#         model = Message
#         fields = ['id', 'ticket', 'sender', 'sender_name', 'content', 'attachment', 'is_read', 'created_at']
#         read_only_fields = ['sender', 'is_read', 'created_at']
        
#     def get_sender_name(self, obj):
#         return obj.sender.get_full_name() or obj.sender.username
        
#     def create(self, validated_data):
#         # Set the sender to the current user
#         validated_data['sender'] = self.context['request'].user
#         return super().create(validated_data)

# class MessageSerializer(serializers.ModelSerializer):
#     sender_name = serializers.SerializerMethodField()
#     attachment_url = serializers.SerializerMethodField()
    
#     class Meta:
#         model = Message
#         fields = ['id', 'ticket', 'sender', 'sender_name', 'content', 'attachment', 'attachment_url', 'is_read', 'created_at']
#         read_only_fields = ['sender', 'is_read', 'created_at', 'attachment_url']
        
#     def get_sender_name(self, obj):
#         return obj.sender.get_full_name() or obj.sender.username
    
#     def get_attachment_url(self, obj):
#         if obj.attachment:
#             request = self.context.get('request')
#             if request:
#                 return request.build_absolute_uri(obj.attachment.url)
#         return None
        
#     def create(self, validated_data):
#         # Set the sender to the current user
#         validated_data['sender'] = self.context['request'].user
#         return super().create(validated_data)

class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    attachment_url = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ['id', 'ticket', 'sender', 'sender_name', 'content', 'attachment', 'attachment_url', 'is_read', 'created_at']
        read_only_fields = ['sender', 'is_read', 'created_at', 'attachment_url']

    def get_sender_name(self, obj):
        return obj.sender.get_full_name() or obj.sender.username

    def get_attachment_url(self, obj):
        if obj.attachment:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.attachment.url)
        return None

    def validate(self, data):
        content = data.get('content', '').strip()
        attachment = data.get('attachment')
        print(attachment,"attachment")
        print(content,"content")

        if not content and not attachment:
            raise serializers.ValidationError("Either content or attachment must be provided.")
        
        return data

    def create(self, validated_data):
        validated_data['sender'] = self.context['request'].user
        return super().create(validated_data)


class TicketHistorySerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    
    class Meta:
        model = TicketHistory
        fields = ['id', 'user', 'user_name', 'action', 'timestamp']
        
    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

class TicketSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    history = TicketHistorySerializer(many=True, read_only=True)
    created_by_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Ticket
        fields = ['id', 'title', 'description', 'created_by', 'created_by_name', 
                 'assigned_to', 'assigned_to_name', 'status', 'priority', 
                 'created_at', 'updated_at', 'messages', 'history']
        read_only_fields = ['created_by', 'created_at', 'updated_at']
        
    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.username
        
    def get_assigned_to_name(self, obj):
        if obj.assigned_to:
            return obj.assigned_to.get_full_name() or obj.assigned_to.username
        return None
        
    def create(self, validated_data):
        # Set the creator to the current user
        validated_data['created_by'] = self.context['request'].user
        ticket = super().create(validated_data)
        
        # Create a history entry for ticket creation
        TicketHistory.objects.create(
            ticket=ticket,
            user=self.context['request'].user,
            action="created this ticket"
        )
        
        return ticket
        
    def update(self, instance, validated_data):
        user = self.context['request'].user
        
        # Track changes for history
        changes = []
        for field, value in validated_data.items():
            old_value = getattr(instance, field)
            if old_value != value:
                if field == 'status':
                    changes.append(f"changed status from {instance.get_status_display()} to {dict(Ticket.STATUS_CHOICES).get(value)}")
                elif field == 'priority':
                    changes.append(f"changed priority from {instance.get_priority_display()} to {dict(Ticket.PRIORITY_CHOICES).get(value)}")
                elif field == 'assigned_to':
                    old_name = old_value.get_full_name() if old_value else "unassigned"
                    new_name = value.get_full_name() if value else "unassigned"
                    changes.append(f"changed assignment from {old_name} to {new_name}")
                else:
                    changes.append(f"updated {field}")
        
        # Update the ticket
        updated_ticket = super().update(instance, validated_data)
        
        # Create history entries for each change
        for change in changes:
            TicketHistory.objects.create(
                ticket=updated_ticket,
                user=user,
                action=change
            )
            
        return updated_ticket

class TicketListSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    unread_messages = serializers.SerializerMethodField()
    
    class Meta:
        model = Ticket
        fields = ['id', 'title', 'created_by_name', 'assigned_to_name', 'description',
                 'status', 'priority', 'created_at', 'updated_at', 'unread_messages']
        
    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.username
        
    def get_assigned_to_name(self, obj):
        if obj.assigned_to:
            return obj.assigned_to.get_full_name() or obj.assigned_to.username
        return None
        
    def get_unread_messages(self, obj):
        user = self.context['request'].user
        return obj.messages.filter(is_read=False).exclude(sender=user).count()

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'first_name', 'last_name']
        
    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user