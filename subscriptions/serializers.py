from rest_framework import serializers
from .models import Subscription, PaymentTransaction
from plans.serializers import PlanSerializer
from users.serializers import UserProfileSerializer
from plans.models import Plan

class PaymentTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = ['id', 'amount', 'transaction_date', 'razorpay_payment_id', 'status', 'currency', 'payment_method']

class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    user = UserProfileSerializer(read_only=True)
    transactions = PaymentTransactionSerializer(many=True, read_only=True)
    
    plan_id = serializers.PrimaryKeyRelatedField(
        queryset=Plan.objects.all(), 
        source='plan', 
        write_only=True
    )

    class Meta:
        model = Subscription
        fields = [
            'id', 'user', 'plan', 'plan_id', 'start_date', 'end_date', 
            'status', 'payment_status', 'razorpay_order_id', 
            'razorpay_payment_id', 'created_at', 'updated_at',
            'transactions'
        ]
        read_only_fields = [
            'id', 'start_date', 'end_date', 'created_at', 
            'updated_at', 'razorpay_order_id', 'razorpay_payment_id'
        ]

    def create(self, validated_data):
        # Set the current user as the subscription user
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)