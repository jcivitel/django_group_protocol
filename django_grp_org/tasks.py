"""
Wiederkehrende Aufgaben der Organisations-App.

Bisher nur eine: das Änderungsprotokoll auf eine Aufbewahrungsfrist bringen.

Warum das dazugehört. Solange nur Stammdaten beobachtet wurden, wuchs
AuditEvent langsam genug, dass es niemandem auffiel. Mit der
Gruppendokumentation ist das anders: ein Protokollabend erzeugt ein Dutzend
Einträge, mal fünf Gruppen, mal fünf Werktage. Ohne Frist wäre die Tabelle
in zwei Jahren größer als die Fachdaten — und die Historie, die sie
nachvollziehbar machen soll, unbenutzbar.

Die Frist ist bewusst großzügig (Vorgabe: drei Jahre) und in der .env
einstellbar. Wer sie auf 0 setzt, schaltet das Aufräumen ab.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("django_grp.audit")


@shared_task(name="django_grp_org.aufraeumen_aenderungsprotokoll")
def aufraeumen_aenderungsprotokoll() -> int:
    """
    Entfernt Einträge, die älter sind als AUDIT_RETENTION_DAYS.

    Gibt die Zahl der entfernten Zeilen zurück, damit ein Lauf im Log
    nachvollziehbar bleibt.
    """
    from .audit import AuditEvent

    tage = getattr(settings, "AUDIT_RETENTION_DAYS", 0)
    if not tage:
        return 0

    grenze = timezone.now() - timezone.timedelta(days=tage)

    # In Häppchen löschen: ein einzelnes DELETE über Hunderttausende Zeilen
    # hält die Tabelle minutenlang, und die Anwendung schreibt weiter hinein.
    entfernt = 0
    while True:
        ids = list(
            AuditEvent.objects.filter(created_at__lt=grenze).values_list(
                "id", flat=True
            )[:1000]
        )
        if not ids:
            break
        anzahl, _ = AuditEvent.objects.filter(id__in=ids).delete()
        entfernt += anzahl

    if entfernt:
        logger.info(
            "Änderungsprotokoll aufgeräumt: %s Einträge älter als %s Tage entfernt",
            entfernt,
            tage,
        )
    return entfernt
