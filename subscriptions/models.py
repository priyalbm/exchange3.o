from django.db import models
from django.conf import settings
from django.utils import timezone
from plans.models import Plan  # Explicitly import Plan from plans app
from auditlog.registry import auditlog
from auditlog.models import AuditlogHistoryField
from datetime import timedelta

class Subscription(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('ACTIVE', 'Active'),
        ('EXPIRED', 'Expired'),
        ('CANCELLED', 'Cancelled')
    ]

    PAYMENT_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed')
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='PENDING')
    
    # Razorpay specific fields
    razorpay_order_id = models.CharField(max_length=255, null=True, blank=True)
    razorpay_payment_id = models.CharField(max_length=255, null=True, blank=True)
    razorpay_signature = models.CharField(max_length=255, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = AuditlogHistoryField()

    def save(self, *args, **kwargs):
        # Auto-set start and end dates based on plan duration
        if self.plan and not self.start_date:
            self.start_date = timezone.now()
            self.end_date = self.start_date + timezone.timedelta(days=self.plan.duration * 30)

        # Update status based on end date
        if self.end_date and timezone.now() > self.end_date:
            self.status = 'EXPIRED'

        super().save(*args, **kwargs)

    def upgrade_plan(self, new_plan):
        """
        Upgrade subscription to a new plan, extending the end date
        """
        old_plan = self.plan
        self.plan = new_plan
        
        # If subscription is still active, add new duration to existing end_date
        if self.status == 'ACTIVE' and self.end_date > timezone.now():
            self.end_date = self.end_date + timezone.timedelta(days=new_plan.duration * 30)
        else:
            # If expired or about to expire, set new start and end dates
            self.start_date = timezone.now()
            self.end_date = self.start_date + timezone.timedelta(days=new_plan.duration * 30)
            
        self.status = 'ACTIVE'
        self.save()
        
        return old_plan, new_plan
    
    def is_expiring_soon(self, days=7):
        """
        Check if subscription will expire in the specified number of days
        """
        if not self.end_date:
            return False
            
        expiry_threshold = timezone.now() + timezone.timedelta(days=days)
        return self.status == 'ACTIVE' and self.end_date <= expiry_threshold

    def __str__(self):
        return f"{self.user.email} - {self.plan.name} Subscription"

class PaymentTransaction(models.Model):
    TRANSACTION_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed')
    ]

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_date = models.DateTimeField(auto_now_add=True)
    razorpay_payment_id = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=20, choices=TRANSACTION_STATUS_CHOICES, default='PENDING')
    
    # Additional payment details
    currency = models.CharField(max_length=10, default='INR')
    payment_method = models.CharField(max_length=50, null=True, blank=True)
    history = AuditlogHistoryField()
    def __str__(self):
        return f"Payment for {self.subscription} - {self.status}"



auditlog.register(Subscription, exclude_fields=['razorpay_signature','razorpay_payment_id','razorpay_order_id'])
auditlog.register(PaymentTransaction, exclude_fields=['razorpay_payment_id'])
