from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("django_grp_frontend.urls")),
    path("api/", include("django_grp_api.urls")),
]
