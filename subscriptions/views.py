import razorpay
from django.conf import settings
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from rest_framework.filters import SearchFilter
from rest_framework.pagination import PageNumberPagination
from .models import Subscription, PaymentTransaction
from .serializers import SubscriptionSerializer, PaymentTransactionSerializer
from plans.models import Plan
from django.utils import timezone
User = get_user_model()

class SubscriptionPagination(PageNumberPagination):
    page_size = 10  # Changed from 1 to a more reasonable 10 items per page
    page_size_query_param = 'page_size'
    max_page_size = 100


class SubscriptionViewSet(viewsets.ModelViewSet):
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = SubscriptionPagination  
    filter_backends = (SearchFilter,)  
    search_fields = ['user__username']

    def get_queryset(self):
        user = self.request.user

        # Admins can filter by user_id query param
        if user.is_authenticated and (user.is_staff or user.is_superuser):
            # user_id = self.request.query_params.get('user_id')
            # if user_id:
                return self.queryset.filter()
            # return self.queryset

        # Regular users only see their own subscriptions
        return self.queryset.filter(user=user)


    @action(detail=True, methods=['GET'])
    def subscription_details(self, request, pk=None):
        """
        Get subscription details by ID
        - Admins can view any subscription
        - Regular users can only view their own subscriptions
        """
        try:
            if request.user.is_staff or request.user.is_superuser:
                subscription = Subscription.objects.get(id=pk)
            else:
                subscription = Subscription.objects.get(id=pk, user=request.user)
                
            serializer = self.get_serializer(subscription)
            return Response(serializer.data)
        except Subscription.DoesNotExist:
            return Response(
                {'error': 'Subscription not found or you do not have permission to view it'}, 
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['GET'])
    def transactions(self, request, pk=None):
        """
        Get all transactions for a specific subscription
        - Admins can view transactions for any subscription
        - Regular users can only view transactions for their own subscriptions
        """
        try:
            if request.user.is_staff or request.user.is_superuser:
                subscription = Subscription.objects.get(id=pk)
            else:
                subscription = Subscription.objects.get(id=pk, user=request.user)
            
            transactions = PaymentTransaction.objects.filter(subscription=subscription)
            serializer = PaymentTransactionSerializer(transactions, many=True)
            return Response(serializer.data)
        except Subscription.DoesNotExist:
            return Response(
                {'error': 'Subscription not found or you do not have permission to view it'}, 
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=['GET'])
    def active_subscription(self, request):
        """
        Get the user's active subscription
        - Admins can view all active subscriptions
        - Regular users can only view their own active subscription
        """
        # If user is admin, return all active subscriptions
        if request.user.is_staff or request.user.is_superuser:
            active_subscriptions = Subscription.objects.filter(status='ACTIVE')
            page = self.paginate_queryset(active_subscriptions)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                return self.get_paginated_response(serializer.data)
            serializer = self.get_serializer(active_subscriptions, many=True)
            return Response(serializer.data)
        
        # For regular users, return only their active subscription
        active_subscription = Subscription.objects.filter(
            user=request.user,
            status='ACTIVE'
        ).first()
        
        if active_subscription:
            serializer = self.get_serializer(active_subscription)
            return Response(serializer.data)
        
        return Response(
            {'error': 'No active subscription'}, 
            status=status.HTTP_404_NOT_FOUND
        )

    @action(detail=False, methods=['POST'])
    def create_order(self, request):
        """
        Create a Razorpay order for subscription
        """
        plan_id = request.data.get('plan_id')
        
        try:
            plan = Plan.objects.get(id=plan_id)
        except Plan.DoesNotExist:
            return Response({'error': 'Plan not found'}, status=status.HTTP_404_NOT_FOUND)

        # Initialize Razorpay client
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

        # Prepare order data
        order_amount = int(plan.price * 100)  # Convert to paise
        order_currency = 'INR'
        order_receipt = f'subscription_{plan_id}_{request.user.id}'

        # Create Razorpay order
        try:
            order = client.order.create({
                'amount': order_amount,
                'currency': order_currency,
                'receipt': order_receipt,
                'payment_capture': 1
            })
            print(order)
            # Create a pending subscription
            subscription = Subscription.objects.create(
                user=request.user,
                plan=plan,
                razorpay_order_id=order['id'],
                status='PENDING',
                payment_status='PENDING'
            )

            return Response({
                'order_id': order['id'],
                'razorpay_key': settings.RAZORPAY_KEY_ID,
                'amount': order_amount,
                'currency': order_currency,
                'subscription_id': subscription.id
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['POST'])
    def verify_payment(self, request):
        """
        Verify Razorpay payment and complete subscription
        """
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        
        razorpay_payment_id = request.data.get('razorpay_payment_id')
        razorpay_order_id = request.data.get('razorpay_order_id')
        razorpay_signature = request.data.get('razorpay_signature')
        subscription_id = request.data.get('subscription_id')

        try:
            # Verify payment signature
            client.utility.verify_payment_signature({
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_order_id': razorpay_order_id,
                'razorpay_signature': razorpay_signature
            })

            # Retrieve payment details
            payment_details = client.payment.fetch(razorpay_payment_id)

            # Update Subscription
            try:
                subscription = Subscription.objects.get(
                    id=subscription_id, 
                    razorpay_order_id=razorpay_order_id
                )
                
                # Update subscription status
                subscription.status = 'ACTIVE'
                subscription.payment_status = 'SUCCESS'
                subscription.razorpay_payment_id = razorpay_payment_id
                subscription.razorpay_signature = razorpay_signature
                subscription.save()

                # Create Payment Transaction
                PaymentTransaction.objects.create(
                    subscription=subscription,
                    amount=subscription.plan.price,
                    razorpay_payment_id=razorpay_payment_id,
                    status='SUCCESS',
                    payment_method=payment_details.get('method', 'Unknown'),
                    currency=payment_details.get('currency', 'INR')
                )

                serializer = self.get_serializer(subscription)
                return Response({
                    'message': 'Payment successful',
                    'subscription': serializer.data
                }, status=status.HTTP_200_OK)

            except Subscription.DoesNotExist:
                return Response({'error': 'Subscription not found'}, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            # Payment verification failed
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        

    @action(detail=True, methods=['POST'])
    def upgrade_plan(self, request, pk=None):
        """
        Upgrade subscription to a new plan
        """
        try:
            # Get the subscription
            if request.user.is_staff or request.user.is_superuser:
                subscription = Subscription.objects.get(id=pk)
            else:
                subscription = Subscription.objects.get(id=pk, user=request.user)
                
            # Get the new plan
            new_plan_id = request.data.get('plan_id')
            if not new_plan_id:
                return Response({'error': 'New plan ID is required'}, status=status.HTTP_400_BAD_REQUEST)
                
            try:
                new_plan = Plan.objects.get(id=new_plan_id)
            except Plan.DoesNotExist:
                return Response({'error': 'New plan not found'}, status=status.HTTP_404_NOT_FOUND)
            
            # Create Razorpay order for the upgrade
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
            
            # Prepare order data
            order_amount = int(new_plan.price * 100)  # Convert to paise
            order_currency = 'INR'
            order_receipt = f'upgrade_{subscription.id}_{new_plan.id}_{request.user.id}'
            
            # Create Razorpay order
            try:
                order = client.order.create({
                    'amount': order_amount,
                    'currency': order_currency,
                    'receipt': order_receipt,
                    'payment_capture': 1
                })
                
                # Update subscription with pending upgrade info
                subscription.razorpay_order_id = order['id']
                subscription.save()
                
                return Response({
                    'order_id': order['id'],
                    'razorpay_key': settings.RAZORPAY_KEY_ID,
                    'amount': order_amount,
                    'currency': order_currency,
                    'subscription_id': subscription.id,
                    'plan_upgrade_id': new_plan.id
                }, status=status.HTTP_201_CREATED)
                
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Subscription.DoesNotExist:
            return Response(
                {'error': 'Subscription not found or you do not have permission to upgrade it'}, 
                status=status.HTTP_404_NOT_FOUND
            )
            
    @action(detail=False, methods=['POST'])
    def verify_upgrade_payment(self, request):
        """
        Verify Razorpay payment and complete plan upgrade
        """
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        
        razorpay_payment_id = request.data.get('razorpay_payment_id')
        razorpay_order_id = request.data.get('razorpay_order_id')
        razorpay_signature = request.data.get('razorpay_signature')
        subscription_id = request.data.get('subscription_id')
        new_plan_id = request.data.get('plan_upgrade_id')
        
        try:
            # Verify payment signature
            client.utility.verify_payment_signature({
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_order_id': razorpay_order_id,
                'razorpay_signature': razorpay_signature
            })
            
            # Retrieve payment details
            payment_details = client.payment.fetch(razorpay_payment_id)
            
            # Update Subscription
            try:
                subscription = Subscription.objects.get(
                    id=subscription_id, 
                    razorpay_order_id=razorpay_order_id
                )
                
                new_plan = Plan.objects.get(id=new_plan_id)
                
                # Perform the plan upgrade
                old_plan, applied_plan = subscription.upgrade_plan(new_plan)
                
                # Update subscription details
                subscription.payment_status = 'SUCCESS'
                subscription.razorpay_payment_id = razorpay_payment_id
                subscription.razorpay_signature = razorpay_signature
                subscription.save()
                
                # Create Payment Transaction
                PaymentTransaction.objects.create(
                    subscription=subscription,
                    amount=applied_plan.price,
                    razorpay_payment_id=razorpay_payment_id,
                    status='SUCCESS',
                    payment_method=payment_details.get('method', 'Unknown'),
                    currency=payment_details.get('currency', 'INR')
                )
                
                serializer = self.get_serializer(subscription)
                return Response({
                    'message': 'Plan upgraded successfully',
                    'subscription': serializer.data
                }, status=status.HTTP_200_OK)
                
            except Subscription.DoesNotExist:
                return Response({'error': 'Subscription not found'}, status=status.HTTP_404_NOT_FOUND)
            except Plan.DoesNotExist:
                return Response({'error': 'Plan not found'}, status=status.HTTP_404_NOT_FOUND)
                
        except Exception as e:
            # Payment verification failed
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['GET'])
    def expiring_soon(self, request):
        """
        Get subscriptions expiring within the next 7 days
        """
        days = int(request.query_params.get('days', 7))
        
        if request.user.is_staff or request.user.is_superuser:
            # For admin users, get all subscriptions expiring soon
            now = timezone.now()
            expiry_threshold = now + timezone.timedelta(days=days)
            
            expiring_subscriptions = Subscription.objects.filter(
                status='ACTIVE',
                end_date__lte=expiry_threshold,
                end_date__gt=now
            )
        else:
            # For regular users, get only their subscriptions expiring soon
            now = timezone.now()
            expiry_threshold = now + timezone.timedelta(days=days)
            
            expiring_subscriptions = Subscription.objects.filter(
                user=request.user,
                status='ACTIVE',
                end_date__lte=expiry_threshold,
                end_date__gt=now
            )
        
        page = self.paginate_queryset(expiring_subscriptions)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
            
        serializer = self.get_serializer(expiring_subscriptions, many=True)
        return Response(serializer.data)


class PaymentTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing payment transactions
    """
    queryset = PaymentTransaction.objects.all()
    serializer_class = PaymentTransactionSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = SubscriptionPagination
    filter_backends = (SearchFilter,)
    search_fields = ['subscription__user__username', 'razorpay_payment_id']

    def get_queryset(self):
        """
        Retrieve transactions based on user type:
        - All logged-in admin users can see all transactions
        - Regular users can only see their own transactions
        """
        user = self.request.user
        if user.is_authenticated and (user.is_staff or user.is_superuser):
            return self.queryset
        return self.queryset.filter(subscription__user=user)