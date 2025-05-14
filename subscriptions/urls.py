from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SubscriptionViewSet,PaymentTransactionViewSet

router = DefaultRouter()
router.register('subscriptions', SubscriptionViewSet, basename='subscription')
router.register('payment-transactions', PaymentTransactionViewSet, basename='payment-transaction')

urlpatterns = [
    path('', include(router.urls)),
]