from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve

urlpatterns = [
    # Core setup & info endpoints on root
    path("", include("django_grp_core.urls")),
    
    # Admin panel
    path("admin/", admin.site.urls),
    
    # API endpoints
    path("api/", include("django_grp_api.urls")),
]

# Medien ausliefern. static() macht das nur bei DEBUG, deshalb steht die
# Route fuer den Containerbetrieb ausgeschrieben da - siehe SERVE_MEDIA.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif settings.SERVE_MEDIA:
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
