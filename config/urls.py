"""
URL configuration for config project.
...
"""
from django.contrib import admin
from django.urls import path, include
from produtividade import views as produtividade_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', produtividade_views.home_redirect_view, name='home'),
    path('produtividade/', include('produtividade.urls')),
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)