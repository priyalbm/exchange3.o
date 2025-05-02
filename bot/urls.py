# from django.urls import path, include
# from rest_framework.routers import DefaultRouter
# from . import views

# router = DefaultRouter()
# router.register(r'exchanges', views.ExchangeViewSet)
# router.register(r'bots', views.BotConfigViewSet)

# urlpatterns = [
#     path('', include(router.urls)),
#     path('pairs/', views.TradingPairAPIView.as_view(), name='trading-pairs'),
#     path('bot/start/', views.BotStartView.as_view(), name='bot-start'),
#     path('bot/stop/', views.BotStopView.as_view(), name='bot-stop'),
#     path('bot/status/', views.BotStatusView.as_view(), name='bot-status'),
#     path('logs/', views.BotLogView.as_view(), name='bot-logs'),
#     path('bot/orders/', views.BotOrderView.as_view(), name='bot-orders'),
#     path('bot/wallet/', views.BotWalletBalanceView.as_view(), name='wallet-operations'),
# ]
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ExchangeViewSet, TradingPairAPIView, BotStartAPIView, 
    BotStopAPIView, BotStatusAPIView, LogsAPIView, OrdersAPIView,
    WalletBalanceAPIView, OrderStatusAPIView, CancelOrderAPIView,
    BotConfigurationViewSet
)

# Create a router for viewsets
router = DefaultRouter()
router.register(r'exchanges', ExchangeViewSet)
router.register(r'bot/configurations', BotConfigurationViewSet)

# URL patterns
urlpatterns = [
    path('', include(router.urls)),
    path('pairs/', TradingPairAPIView.as_view(), name='trading-pairs'),
    path('bot/start/', BotStartAPIView.as_view(), name='bot-start'),
    path('bot/stop/', BotStopAPIView.as_view(), name='bot-stop'),
    path('bot/status/', BotStatusAPIView.as_view(), name='bot-status'),
    path('wallet/balance/', WalletBalanceAPIView.as_view(), name='wallet-balance'),
    path('orders/status/', OrderStatusAPIView.as_view(), name='order-status'),
    path('orders/cancel/', CancelOrderAPIView.as_view(), name='cancel-order'),
    path('logs/', LogsAPIView.as_view(), name='logs'),
    path('orders/', OrdersAPIView.as_view(), name='orders'),
]
