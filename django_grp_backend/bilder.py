"""
Fotos verkleinern - im Hintergrund, wenn möglich.

Ein Portrait aus einer Handykamera hat mehrere Megabyte; angezeigt wird es
als Kreis von vierzig Pixeln. Verkleinern lohnt sich also — nur nicht im
Request-Thread: `Image.open(...)` liest die Datei, dekodiert sie, skaliert und
schreibt zurück, und die Person, die auf „Speichern" gedrückt hat, wartet die
ganze Zeit auf eine drehende Scheibe.

Deshalb läuft es über Celery, wenn ein Broker da ist, und sonst direkt. Das
ist dasselbe Muster wie beim Mailversand (django_grp_mail/service.py): der
Ausfall des Brokers darf keine Funktion kosten, nur die Verzögerung.

`.path` funktioniert nur mit lokalem Storage. Das ist hier der Fall; sollte
später ein Objektspeicher dazukommen, ist diese Datei die eine Stelle, die es
merkt.
"""

import logging

from celery import shared_task
from PIL import Image

logger = logging.getLogger("django_grp.bilder")

# Kantenlänge, auf die verkleinert wird. Reicht für eine Detailansicht und
# ist klein genug, dass ein Dutzend Bilder eine Liste nicht ausbremst.
MAX_KANTE = 800


def verkleinern(pfad: str) -> bool:
    """Verkleinert die Datei an Ort und Stelle. True, wenn etwas passiert ist."""
    try:
        with Image.open(pfad) as bild:
            if bild.height <= MAX_KANTE and bild.width <= MAX_KANTE:
                return False
            bild.thumbnail((MAX_KANTE, MAX_KANTE))
            bild.save(pfad)
        return True
    except (OSError, ValueError):
        # Ein kaputtes oder verschwundenes Bild darf kein Speichern kippen -
        # der Datensatz ist zu dem Zeitpunkt längst geschrieben.
        logger.exception("Bild ließ sich nicht verkleinern: %s", pfad)
        return False


@shared_task(name="django_grp_backend.bild_verkleinern")
def bild_verkleinern(pfad: str) -> bool:
    return verkleinern(pfad)


def einplanen(feld) -> None:
    """
    Stößt das Verkleinern an - über Celery, sonst sofort.

    `feld` ist ein ImageField-Wert (resident.picture). Fehlt die Datei, ist
    nichts zu tun.
    """
    if not feld:
        return

    try:
        pfad = feld.path
    except (ValueError, NotImplementedError):
        # Kein lokaler Speicher - dann gibt es hier nichts zu skalieren.
        return

    try:
        bild_verkleinern.delay(pfad)
    except Exception:  # noqa: BLE001 - Broker weg, Kombu-Fehler, kein Celery
        logger.warning("Celery nicht erreichbar, Bild wird direkt verkleinert")
        verkleinern(pfad)
