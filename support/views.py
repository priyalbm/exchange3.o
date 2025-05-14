from rest_framework import viewsets, permissions, status, generics, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from .models import Ticket, Message, TicketHistory
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.contrib.auth.models import User
from django.contrib.auth import get_user_model
from .serializers import (
    TicketSerializer,
    TicketListSerializer,
    MessageSerializer,
    UserSerializer,
    UserRegistrationSerializer,
)

User = get_user_model()
class IsAdminOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_staff or request.user.is_superuser

class IsTicketCreatorOrAdmin(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        # Allow get, head, options requests
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Allow if user is ticket creator or admin
        return obj.created_by == request.user or request.user.is_staff or request.user.is_superuser

class UserRegistrationView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    @action(detail=False, methods=['get'])
    def me(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def admins(self, request):
        admins = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True))
        serializer = self.get_serializer(admins, many=True)
        return Response(serializer.data)

class TicketViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsTicketCreatorOrAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'description', 'status', 'priority']
    ordering_fields = ['created_at', 'updated_at', 'status', 'priority']
    
    def get_queryset(self):
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return Ticket.objects.all()
        return Ticket.objects.filter(created_by=user)
    
    def get_serializer_class(self):
        if self.action == 'list':
            return TicketListSerializer
        return TicketSerializer
    
    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        ticket = self.get_object()
        try:
            user_id = request.data.get('user_id')
            if user_id:
                assignee = User.objects.get(id=user_id)
                ticket.assigned_to = assignee
            else:
                ticket.assigned_to = None
            
            ticket.save()
            
            # Create history entry
            assignee_name = assignee.get_full_name() if user_id else "unassigned"
            TicketHistory.objects.create(
                ticket=ticket,
                user=request.user,
                action=f"assigned ticket to {assignee_name}"
            )
            
            serializer = self.get_serializer(ticket)
            return Response(serializer.data)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=True, methods=['post'])
    def change_status(self, request, pk=None):
        ticket = self.get_object()
        status_value = request.data.get('status')
        
        if not status_value or status_value not in dict(Ticket.STATUS_CHOICES):
            return Response({"error": "Invalid status"}, status=status.HTTP_400_BAD_REQUEST)
            
        old_status = ticket.get_status_display()
        ticket.status = status_value
        ticket.save()
        
        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            user=request.user,
            action=f"changed status from {old_status} to {dict(Ticket.STATUS_CHOICES).get(status_value)}"
        )
        
        serializer = self.get_serializer(ticket)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def change_priority(self, request, pk=None):
        ticket = self.get_object()
        priority_value = request.data.get('priority')
        
        if not priority_value or priority_value not in dict(Ticket.PRIORITY_CHOICES):
            return Response({"error": "Invalid priority"}, status=status.HTTP_400_BAD_REQUEST)
            
        old_priority = ticket.get_priority_display()
        ticket.priority = priority_value
        ticket.save()
        
        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            user=request.user,
            action=f"changed priority from {old_priority} to {dict(Ticket.PRIORITY_CHOICES).get(priority_value)}"
        )
        
        serializer = self.get_serializer(ticket)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        ticket = self.get_object()
        histories = ticket.history.all()
        from .serializers import TicketHistorySerializer
        serializer = TicketHistorySerializer(histories, many=True)
        return Response(serializer.data)

# class MessageViewSet(viewsets.ModelViewSet):
#     serializer_class = MessageSerializer
#     permission_classes = [permissions.IsAuthenticated]
    
#     def get_queryset(self):
#         ticket_id = self.request.query_params.get('ticket')
#         user = self.request.user

#         if not ticket_id:
#             return Message.objects.none()

#         # Check if user is admin (is_staff or is_superuser) or involved in the ticket
#         if user.is_staff or user.is_superuser:
#             return Message.objects.filter(ticket_id=ticket_id).order_by('created_at')

#         return Message.objects.filter(ticket_id=ticket_id).filter(
#             Q(sender=user) | Q(recipient=user)  # Adjust according to your model
#         ).order_by('created_at')

#         # return Message.objects.all()
    
#     def create(self, request, *args, **kwargs):
#         ticket_id = request.data.get('ticket')
        
#         # Verify the ticket exists and user has access
#         try:
#             ticket = Ticket.objects.get(id=ticket_id)
#             user = request.user
            
#             # Check if user is allowed to send messages to this ticket
#             if not (user.is_staff or user.is_superuser or ticket.created_by == user or ticket.assigned_to == user):
#                 return Response(
#                     {"error": "You do not have permission to send messages to this ticket"},
#                     status=status.HTTP_403_FORBIDDEN
#                 )
                
#             response = super().create(request, *args, **kwargs)
            
#             # Create history entry
#             TicketHistory.objects.create(
#                 ticket=ticket,
#                 user=request.user,
#                 action="added a new message"
#             )
            
#             return response
            
#         except Ticket.DoesNotExist:
#             return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)
    
#     @action(detail=False, methods=['post'])
#     def mark_as_read(self, request):
#         ticket_id = request.data.get('ticket')
#         message_ids = request.data.get('message_ids', [])
        
#         if not ticket_id:
#             return Response({"error": "Ticket ID is required"}, status=status.HTTP_400_BAD_REQUEST)
            
#         try:
#             ticket = Ticket.objects.get(id=ticket_id)
#             user = request.user
            
#             # Check if user has access to this ticket
#             if not (user.is_staff or user.is_superuser or ticket.created_by == user or ticket.assigned_to == user):
#                 return Response(
#                     {"error": "You do not have permission to access this ticket"},
#                     status=status.HTTP_403_FORBIDDEN
#                 )
                
#             # Mark messages as read
#             query = Message.objects.filter(ticket=ticket).exclude(sender=user)
#             if message_ids:
#                 query = query.filter(id__in=message_ids)
                
#             count = query.update(is_read=True)
            
#             return Response({"success": True, "marked_count": count})
            
#         except Ticket.DoesNotExist:
#             return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)

class MessageViewSet(viewsets.ModelViewSet):
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def get_queryset(self):
        ticket_id = self.request.query_params.get('ticket')
        user = self.request.user

        if not ticket_id:
            return Message.objects.none()

        # Check if user is admin (is_staff or is_superuser) or involved in the ticket
        if user.is_staff or user.is_superuser:
            return Message.objects.filter(ticket_id=ticket_id).order_by('created_at')

        # Filter for regular users who created the ticket or are assigned to it
        ticket = get_object_or_404(Ticket, id=ticket_id)
        if ticket.created_by == user or ticket.assigned_to == user:
            return Message.objects.filter(ticket_id=ticket_id).order_by('created_at')
            
        return Message.objects.none()
    
    @action(detail=False, methods=['post'])
    def mark_as_read(self, request):
        ticket_id = request.data.get('ticket')
        message_ids = request.data.get('message_ids', [])
        
        if not ticket_id:
            return Response({"error": "Ticket ID is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            user = request.user
            
            # Check if user has access to this ticket
            if not (user.is_staff or user.is_superuser or ticket.created_by == user or ticket.assigned_to == user):
                return Response(
                    {"error": "You do not have permission to access this ticket"},
                    status=status.HTTP_403_FORBIDDEN
                )
                
            # Mark messages as read
            query = Message.objects.filter(ticket=ticket).exclude(sender=user)
            if message_ids:
                query = query.filter(id__in=message_ids)
                
            count = query.update(is_read=True)
            
            return Response({"success": True, "marked_count": count})
            
        except Ticket.DoesNotExist:
            return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)
    
    def create(self, request, *args, **kwargs):
        ticket_id = request.data.get('ticket')
        
        # Verify the ticket exists and user has access
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            user = request.user
            
            # Check if user is allowed to send messages to this ticket
            if not (user.is_staff or user.is_superuser or ticket.created_by == user or ticket.assigned_to == user):
                return Response(
                    {"error": "You do not have permission to send messages to this ticket"},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Handle file upload
            response = super().create(request, *args, **kwargs)
            
            # Create history entry
            TicketHistory.objects.create(
                ticket=ticket,
                user=request.user,
                action="added a new message" + (" with attachment" if request.data.get('attachment') else "")
            )
            
            return response
            
        except Ticket.DoesNotExist:
            return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=True, methods=['get'])
    def download_attachment(self, request, pk=None):
        message = self.get_object()
        if not message.attachment:
            return Response({"error": "No attachment found"}, status=status.HTTP_404_NOT_FOUND)
        
        # Check if user has access to this ticket's attachments
        ticket = message.ticket
        user = request.user
        if not (user.is_staff or user.is_superuser or ticket.created_by == user or ticket.assigned_to == user):
            return Response(
                {"error": "You do not have permission to download this attachment"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Serve the file using FileResponse
        from django.http import FileResponse
        try:
            return FileResponse(message.attachment.open(), as_attachment=True)
        except Exception as e:
            return Response({"error": f"Error downloading file: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)