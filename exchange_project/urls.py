from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('users.urls')),
    path('api/', include('plans.urls')),
    path('api/support/', include('support.urls')),
    path('api/', include('subscriptions.urls')),
    path('api/notifications/', include('notifications2.urls')),
    # path('api/', include('crypto_bot.urls')),
     path('api/', include('bot.urls')),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
