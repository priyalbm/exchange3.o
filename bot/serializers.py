from rest_framework import serializers
from .models import Exchange, BotConfiguration, TradeOrder, BotLog
from plans.models import Plan
from plans.serializers import PlanSerializer

class ExchangeSerializer(serializers.ModelSerializer):
    plans = serializers.SerializerMethodField()
    lowest_price = serializers.SerializerMethodField()
    class Meta:
        model = Exchange
        fields = ['id', 'name', 'description','pair_link','api_endpoint', 'is_active','plans', 'lowest_price']

    def get_plans(self, obj):
        plans = Plan.objects.filter(exchange_id=obj.id)
        return PlanSerializer(plans, many=True).data
    
    def get_lowest_price(self, obj):
        plans = Plan.objects.filter(exchange_id=obj.id)
        if plans.exists():
            return min(plan.price for plan in plans)
        return None


# TradingPairSerializer is replaced with a simple serializer for API response
class TradingPairSerializer(serializers.Serializer):
    symbol = serializers.CharField(max_length=20)
    base_asset = serializers.CharField(max_length=10)
    quote_asset = serializers.CharField(max_length=10)
    min_quantity = serializers.CharField(max_length=20)
    max_quantity = serializers.CharField(max_length=20, allow_null=True)
    price_precision = serializers.IntegerField()
    quantity_precision = serializers.IntegerField()


class BotConfigurationSerializer(serializers.ModelSerializer):
    exchange_name = serializers.CharField(source='exchange.name', read_only=True)
    user_name = serializers.CharField(source='user.username', read_only=True)
    class Meta:
        model = BotConfiguration
        fields = [
            'id', 'exchange', 'exchange_name', 'pair_symbol', 'status', 'user','user_name','memo',
            'api_key', 'secret_key', 'decimal_precision', 'risk_tolerance',
            'trade_volume', 'time_interval', 'is_active','created_at'
        ]
        extra_kwargs = {
            'api_key': {'write_only': True},
            'secret_key': {'write_only': True},
            'user': {'required': False, 'read_only': True},  # Make user optional for input
        }

class TradeOrderSerializer(serializers.ModelSerializer):
    bot_configuration_id = serializers.IntegerField(source='bot_configuration.id', read_only=True)
    
    class Meta:
        model = TradeOrder
        fields = [
            'id', 'bot_configuration_id', 'order_type', 'exchange_order_id',
            'symbol', 'price', 'quantity', 'status', 'created_at', 'updated_at', 'filled_at'
        ]
        read_only_fields = [
            'id', 'bot_configuration_id', 'exchange_order_id', 'created_at', 'updated_at', 'filled_at'
        ]


class BotLogSerializer(serializers.ModelSerializer):
    bot_configuration_id = serializers.IntegerField(source='bot_configuration.id', read_only=True)
    exchange_name = serializers.CharField(source='bot_configuration.exchange.name', read_only=True)
    pair = serializers.CharField(source='bot_configuration.pair_symbol', read_only=True)
    user_id = serializers.IntegerField(source='bot_configuration.user.id', read_only=True)
    username = serializers.CharField(source='bot_configuration.user.username', read_only=True)
    log_type = serializers.SerializerMethodField()
    
    class Meta:
        model = BotLog
        fields = ['id', 'bot_configuration_id', 'exchange_name', 'pair', 'user_id', 
                  'username', 'level', 'message', 'created_at', 'log_type']
        read_only_fields = ['id', 'created_at', 'log_type']
    
    def get_log_type(self, obj):
        """
        Determine if this is a user action log (start/stop) or a bot operation log
        """
        message = obj.message.lower()
        if ('bot started' in message or 'bot stopped' in message or 
            'start bot' in message or 'stop bot' in message):
            return 'user_action'
        return 'bot_operation'

class BotStartSerializer(serializers.Serializer):
    exchange = serializers.CharField(max_length=50)
    api_key = serializers.CharField(max_length=255)
    secret_key = serializers.CharField(max_length=255)
    pair = serializers.CharField(max_length=20)
    decimal_precision = serializers.IntegerField(min_value=0, max_value=8)
    risk_tolerance = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0.01)
    trade_volume = serializers.DecimalField(max_digits=18, decimal_places=8, min_value=0.00000001)
    time_interval = serializers.IntegerField(min_value=1)


class BotStopSerializer(serializers.Serializer):
    bot_id = serializers.IntegerField()
    
    
class WalletBalanceRequestSerializer(serializers.Serializer):
    exchange = serializers.CharField(max_length=50)
    api_key = serializers.CharField(max_length=255)
    secret_key = serializers.CharField(max_length=255)
    
    
class CancelOrderSerializer(serializers.Serializer):
    bot_id = serializers.IntegerField()
    order_id = serializers.CharField(max_length=100, required=False)
    cancel_all = serializers.BooleanField(default=False)

class BotUpdateSerializer(BotConfigurationSerializer):
    """
    Serializer specifically for updates that makes all fields optional.
    """
    class Meta(BotConfigurationSerializer.Meta):
        # Make all fields optional for updates
        extra_kwargs = {
            'exchange': {'required': False},
            'pair_symbol': {'required': False},
            'api_key': {'required': False, 'write_only': True},
            'secret_key': {'required': False, 'write_only': True},
            'decimal_precision': {'required': False},
            'risk_tolerance': {'required': False},
            'trade_volume': {'required': False},
            'time_interval': {'required': False},
            'user': {'required': False, 'read_only': True},
        }   
    
class OrderCheckSerializer(serializers.Serializer):
    bot_id = serializers.IntegerField()
    order_id = serializers.CharField(max_length=100, required=False)
