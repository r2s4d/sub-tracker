from django.contrib import admin
from django.urls import include, path

from core.views import home

urlpatterns = [
    path('', home, name='home'),
    path('accounts/', include('accounts.urls')),
    path('subscriptions/', include('subscriptions.urls')),
    path('admin/', admin.site.urls),
]
