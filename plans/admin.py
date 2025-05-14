from django.contrib import admin
from .models import Plan

class PlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'price', 'duration', 'description')
    search_fields = ('name', 'description')
    list_filter = ('duration',)
    ordering = ('price',)

admin.site.register(Plan, PlanAdmin)
