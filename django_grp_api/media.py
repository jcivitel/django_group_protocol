"""
Medien nur an die, die sie sehen duerfen.

Bisher lieferte Django alles unter MEDIA_ROOT ueber django.views.static.serve
aus - ohne Anmeldung, ohne Rechtepruefung (S4 der Analyse). Darin liegen
Fotos von Kindern in Hilfe zur Erziehung, Briefboegen der Gruppen und
exportierte Protokolle. Wer einen Pfad kannte oder riet, kam heran; der
Proxy im Frontend prueft nur, OB ein Cookie da ist, nicht wessen.

Hier laeuft es andersherum: der Pfad allein berechtigt zu nichts. Zu jeder
Datei wird der Datensatz gesucht, an dem sie haengt, und der wird gegen das
anfragende Konto geprueft - dieselbe `for_user`-Regel wie ueberall sonst.

Was nicht zugeordnet werden kann, wird nicht ausgeliefert. Eine verwaiste
Datei in MEDIA_ROOT ist kein Grund, sie herauszugeben.
"""

import logging
import mimetypes
import os

from django.conf import settings
from django.http import FileResponse
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from django_grp_backend.models import Group, Protocol, Resident

logger = logging.getLogger("django_grp.api")


def _bewohnerfoto(user, name: str) -> bool:
    return Resident.objects.for_user(user).filter(picture=name).exists()


def _personalfoto(user, name: str) -> bool:
    """
    Personalfotos haengen am Traeger, nicht an einer Gruppe.

    Der Import steht in der Funktion und nicht oben: django_grp_backend soll
    django_grp_org nicht zur Ladezeit brauchen - dieselbe Ruecksicht, die
    access.py nimmt.
    """
    from django_grp_org.models import Employee
    from django_grp_org.tenancy import limit_to_tenant

    return limit_to_tenant(Employee.objects.filter(picture=name), user).exists()


def _briefbogen(user, name: str) -> bool:
    return Group.objects.for_user(user).filter(pdf_template=name).exists()


def _protokollexport(user, name: str) -> bool:
    return Protocol.objects.for_user(user).filter(exported_file=name).exists()


# Welcher Ordner zu welcher Pruefung gehoert. Die Praefixe stammen aus den
# upload_to-Angaben der Modelle: RandomizedFileName schreibt nach "images/",
# Group.pdf_template nach "docs/", Protocol.exported_file nach "exports/".
PRUEFUNGEN = {
    "images": (_bewohnerfoto, _personalfoto),
    "docs": (_briefbogen,),
    "exports": (_protokollexport,),
}


def darf_lesen(user, name: str) -> bool:
    ordner = name.split("/", 1)[0]
    for pruefung in PRUEFUNGEN.get(ordner, ()):
        if pruefung(user, name):
            return True
    return False


class MediaView(APIView):
    """
    GET /api/v1/media/<pfad>

    Liefert eine Datei aus MEDIA_ROOT, wenn das Konto den Datensatz sehen
    darf, an dem sie haengt.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, path: str):
        wurzel = os.path.realpath(settings.MEDIA_ROOT)
        ziel = os.path.realpath(os.path.join(wurzel, path))

        # Erst den Pfad festnageln, dann alles Weitere. "../" darf nicht aus
        # MEDIA_ROOT herausfuehren, auch nicht ueber einen Symlink.
        if os.path.commonpath([ziel, wurzel]) != wurzel:
            logger.warning("Medienzugriff ausserhalb von MEDIA_ROOT: %s", path)
            raise NotFound("Datei nicht gefunden.")

        # Der Name, wie er im Datenbankfeld steht: relativ zu MEDIA_ROOT,
        # mit Schraegstrichen - auch unter Windows.
        name = os.path.relpath(ziel, wurzel).replace(os.sep, "/")

        if not darf_lesen(request.user, name):
            # 403 und nicht 404: dass es die Datei gibt, verraet der Pfad
            # ohnehin dem, der ihn hat. Was zaehlt, ist dass er nichts
            # bekommt.
            raise PermissionDenied("Kein Zugriff auf diese Datei.")

        if not os.path.isfile(ziel):
            raise NotFound("Datei nicht gefunden.")

        typ = mimetypes.guess_type(ziel)[0] or "application/octet-stream"
        antwort = FileResponse(open(ziel, "rb"), content_type=typ)
        antwort["Cache-Control"] = "private, max-age=60"
        antwort["X-Content-Type-Options"] = "nosniff"
        # Kein inline-Rendern fremder Dateitypen im Browser-Kontext.
        if typ not in ("image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"):
            antwort["Content-Disposition"] = f'attachment; filename="{os.path.basename(ziel)}"'
        return antwort
