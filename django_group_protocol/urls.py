from django.conf import settings
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve

urlpatterns = [
    # Einrichtung und Betriebszustand
    path("", include("django_grp_core.urls")),
    # Django-Verwaltung
    path("admin/", admin.site.urls),
    # API
    path("api/", include("django_grp_api.urls")),
]

# Medien.
#
# Hier stand frueher django.views.static.serve ohne jede Pruefung - und damit
# waren Bewohnerfotos, Briefboegen und exportierte Protokolle fuer jeden
# erreichbar, der den Pfad kannte (S4). Der Weg fuer die Anwendung ist jetzt
# /api/v1/media/<pfad>: dort wird zu jeder Datei der Datensatz gesucht, an dem
# sie haengt, und gegen das anfragende Konto geprueft.
#
# SERVE_MEDIA bleibt als Notausgang fuer die oertliche Entwicklung, ist aber
# nicht mehr die Vorgabe und im Docker-Compose ausgeschaltet.
if settings.SERVE_MEDIA:
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
