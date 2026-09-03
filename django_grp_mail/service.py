"""
Mails einstellen und verschicken.

Der Weg ist immer derselbe: einstellen() schreibt die Zeile in den
Postausgang, versenden() holt sie und schickt sie weg. Dazwischen liegt
Celery - oder auch nicht, denn beides funktioniert auch ohne.

Genau das ist der Grund fuer die Trennung: faellt der Broker aus, ist die
Mail trotzdem festgehalten. Sie geht dann eben spaeter raus, statt verloren
zu sein.
"""

import logging

from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

from .models import MailMessage, MailSettings

logger = logging.getLogger("django_grp.mail")


def verbindung(einstellungen: MailSettings):
    """
    Baut die SMTP-Verbindung aus den Einstellungen der Datenbank.

    Nicht ueber die EMAIL_*-Settings von Django: die stehen beim Start fest,
    und die Verwaltung soll den Server im Frontend wechseln koennen, ohne
    dass jemand den Container neu startet.
    """
    return get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=einstellungen.host,
        port=einstellungen.port,
        username=einstellungen.username or None,
        password=einstellungen.password or None,
        use_tls=einstellungen.use_tls,
        use_ssl=einstellungen.use_ssl,
        timeout=einstellungen.timeout_seconds,
        fail_silently=False,
    )


def einstellen(*, to: str, subject: str, body: str, kind: str = "test") -> MailMessage:
    """
    Legt die Mail in den Postausgang und stoesst den Versand an.

    Der Versand laeuft ueber Celery, wenn ein Broker erreichbar ist, sonst
    sofort im laufenden Vorgang. Wer eine Abwesenheit genehmigt, soll keine
    Fehlerseite bekommen, bloss weil Redis gerade nicht da ist.
    """
    nachricht = MailMessage.objects.create(
        to_address=to, subject=subject, body=body, kind=kind
    )

    try:
        from .tasks import versenden_task

        versenden_task.delay(nachricht.id)
    except Exception:  # noqa: BLE001 - Broker weg, Kombu-Fehler, kein Celery
        logger.warning(
            "Celery nicht erreichbar, Mail %s wird direkt verschickt", nachricht.id
        )
        versenden(nachricht.id)

    return nachricht


def versenden(nachricht_id: int) -> MailMessage | None:
    """
    Schickt eine Mail aus dem Postausgang.

    Gibt den Datensatz zurueck, damit der Aufrufer den Stand ablesen kann -
    die Testmail im Frontend zeigt damit sofort, ob es geklappt hat.
    """
    nachricht = MailMessage.objects.filter(id=nachricht_id).first()
    if nachricht is None:
        logger.warning("Mail %s gibt es nicht mehr", nachricht_id)
        return None
    if nachricht.status == "sent":
        return nachricht

    einstellungen = MailSettings.laden()
    if not einstellungen.ready:
        # Kein Fehler, sondern ein Zustand: der Versand ist aus oder noch
        # nicht eingerichtet. Die Mail bleibt als Beleg stehen.
        nachricht.status = "skipped"
        nachricht.error = (
            "Der Versand ist nicht eingerichtet oder ausgeschaltet."
            if not einstellungen.enabled
            else "Es fehlen Server oder Absenderadresse."
        )
        nachricht.save(update_fields=["status", "error"])
        return nachricht

    nachricht.status = "sending"
    nachricht.attempts += 1
    nachricht.save(update_fields=["status", "attempts"])

    try:
        EmailMessage(
            subject=nachricht.subject,
            body=nachricht.body,
            from_email=einstellungen.absender,
            to=[nachricht.to_address],
            connection=verbindung(einstellungen),
        ).send()
    except Exception as fehler:  # noqa: BLE001 - SMTP wirft vieles
        nachricht.status = "failed"
        nachricht.error = str(fehler)[:2000]
        nachricht.save(update_fields=["status", "error"])
        logger.exception("Mail %s fehlgeschlagen", nachricht_id)
        return nachricht

    nachricht.status = "sent"
    nachricht.error = ""
    nachricht.sent_at = timezone.now()
    nachricht.save(update_fields=["status", "error", "sent_at"])
    return nachricht
