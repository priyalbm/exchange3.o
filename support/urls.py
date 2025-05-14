from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import (
    UserViewSet,
    TicketViewSet,
    MessageViewSet,
    UserRegistrationView,
)

router = DefaultRouter()
router.register('tickets', TicketViewSet, basename='ticket')
router.register('messages', MessageViewSet, basename='message')

urlpatterns = [
    path('', include(router.urls)),
]

