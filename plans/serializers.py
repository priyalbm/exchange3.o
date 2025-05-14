# from rest_framework import serializers
# from .models import Plan
# from crypto_bot.models import Exchange  # Import the Exchange model

# class PlanSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = Plan
#         fields = ['id', 'name', 'description', 'price', 'duration', 'features']
# serializers.py (plan app)
from rest_framework import serializers
from bot.models import Exchange  # Import the Exchange model
from .models import Plan

class ExchangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exchange
        fields = ['id', 'name', 'base_url', 'description']  # Fields for Exchange model


class PlanSerializer(serializers.ModelSerializer):
    exchange = serializers.PrimaryKeyRelatedField(queryset=Exchange.objects.all())  # <== THIS LINE IS KEY

    class Meta:
        model = Plan
        fields = ['id', 'name', 'description', 'price', 'duration', 'features', 'exchange']
