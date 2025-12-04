from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Core setup & info endpoints on root
    path("", include("django_grp_core.urls")),
    
    # Admin panel
    path("admin/", admin.site.urls),
    
    # API endpoints
    path("api/", include("django_grp_api.urls")),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
