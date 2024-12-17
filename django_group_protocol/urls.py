from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("django_grp_frontend.urls")),
    path("api/", include("django_grp_api.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
