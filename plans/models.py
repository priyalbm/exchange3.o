from django.db import models
from auditlog.registry import auditlog
from auditlog.models import AuditlogHistoryField
from bot.models import Exchange

class Plan(models.Model):
    name = models.CharField(max_length=255,unique=True)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration = models.PositiveIntegerField()  # duration in months
    features = models.JSONField()   
    exchange = models.ForeignKey(Exchange, on_delete=models.CASCADE, related_name='plans',default=1)  # New field  # Stores a list of features in JSON format
    history = AuditlogHistoryField()

    def __str__(self):
        return self.name
    
auditlog.register(Plan)
