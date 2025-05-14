from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
User = get_user_model()

class Exchange(models.Model):
    """
    Model to store information about supported cryptocurrency exchanges
    """
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    api_endpoint=models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    pair_link=models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


# TradingPair model has been removed as we now fetch pairs directly from exchange APIs
# instead of storing them in the database


class BotConfiguration(models.Model):
    """
    Model to store bot trading configurations
    """
    exchange = models.ForeignKey(Exchange, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bot_configurations')
    pair_symbol = models.CharField(max_length=20, default="BTC_USDT", help_text="Trading pair symbol (e.g., BTC_USDT)")
    api_key = models.CharField(max_length=255)
    secret_key = models.CharField(max_length=255)
    memo = models.CharField(max_length=255,default="test")
    status = models.CharField(max_length=255,default="idle")
    decimal_precision = models.IntegerField(default=4)
    risk_tolerance = models.DecimalField(max_digits=5, decimal_places=2)
    trade_volume = models.DecimalField(max_digits=18, decimal_places=8)
    time_interval = models.IntegerField(default=10)  # in seconds
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Bot for {self.exchange.name} - {self.pair_symbol}"


class TradeOrder(models.Model):
    """
    Model to store trade orders placed by the bot
    """
    ORDER_TYPES = [
        ('buy', 'Buy'),
        ('sell', 'Sell'),
    ]
    ORDER_STATUS = [
        ('open', 'Open'),
        ('filled', 'Filled'),
        ('partially_filled', 'Partially Filled'),
        ('canceled', 'Canceled'),
        ('rejected', 'Rejected'),
    ]

    bot_configuration = models.ForeignKey(BotConfiguration, on_delete=models.CASCADE, related_name='orders')
    order_type = models.CharField(max_length=10, choices=ORDER_TYPES)
    exchange_order_id = models.CharField(max_length=100, null=True, blank=True)
    symbol = models.CharField(max_length=20)
    price = models.DecimalField(max_digits=18, decimal_places=8)
    quantity = models.DecimalField(max_digits=18, decimal_places=8)
    status = models.CharField(max_length=20, choices=ORDER_STATUS, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    filled_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.order_type.upper()} {self.quantity} {self.symbol} @ {self.price}"
    
    def mark_as_filled(self):
        self.status = 'filled'
        self.filled_at = timezone.now()
        self.save()


class BotLog(models.Model):
    """
    Model to store logs of bot operations
    """
    LOG_LEVELS = [
        ('INFO', 'Info'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
        ('DEBUG', 'Debug'),
    ]

    bot_configuration = models.ForeignKey(BotConfiguration, on_delete=models.CASCADE, related_name='logs')
    level = models.CharField(max_length=10, choices=LOG_LEVELS, default='INFO')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.level}] {self.created_at.strftime('%Y-%m-%d %H:%M:%S')} - {self.message[:50]}"
