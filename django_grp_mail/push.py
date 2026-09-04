"""
Push-Benachrichtigungen (Web Push, RFC 8030).

Der zweite Weg neben der E-Mail, und der schnellere: eine Mail liest man,
wenn man das nächste Mal ins Postfach schaut, eine Push-Nachricht kommt an,
während man auf dem Weg zur Gruppe ist. Für "dein Dienst morgen ist
getauscht" ist das der Unterschied zwischen Bescheid wissen und nicht.

**Wie es funktioniert.** Der Browser meldet sich beim Push-Dienst seines
Herstellers an (Google, Mozilla, Apple) und gibt der Anwendung eine Adresse
samt zwei Schlüsseln. Damit lässt sich eine verschlüsselte Nachricht an
genau dieses Gerät schicken - ohne dass der Hersteller mitlesen könnte und
ohne dass wir eine Verbindung offen halten müssten.

**VAPID.** Die Schlüssel weisen den Absender aus. Sie stehen als Einstellung
in der Datenbank, nicht in einer .env - aus demselben Grund wie beim
Mailserver: die Verwaltung soll den Versand einrichten können, ohne jemanden
mit Serverzugang zu brauchen. Der private Schlüssel liegt verschlüsselt.

**Was hier bewusst nicht passiert.** Kein Inhalt, der nicht auf einen
Sperrbildschirm gehört. Eine Push-Nachricht erscheint, ohne dass jemand sich
anmeldet, oft vor fremden Augen - deshalb steht dort "Dein Antrag wurde
entschieden" und nicht, worum es ging. Das Wesentliche steht in der
Anwendung, hinter der Anmeldung.
"""

import json
import logging

from django.conf import settings

logger = logging.getLogger("django_grp.push")


def schluesselpaar() -> tuple[str, str]:
    """
    Erzeugt ein neues VAPID-Schluesselpaar (privat, oeffentlich).

    Beide im base64url-Format ohne Fuellzeichen, wie die Push-Dienste es
    erwarten. Wird der private Schluessel gewechselt, verlieren alle
    bestehenden Anmeldungen ihre Gueltigkeit - deshalb passiert das nur auf
    ausdrueckliche Anforderung und nicht etwa beim Start.
    """
    import base64

    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())

    privat = key.private_numbers().private_value.to_bytes(32, "big")
    zahlen = key.public_key().public_numbers()
    oeffentlich = (
        b"\x04" + zahlen.x.to_bytes(32, "big") + zahlen.y.to_bytes(32, "big")
    )

    def kodieren(rohdaten: bytes) -> str:
        return base64.urlsafe_b64encode(rohdaten).decode().rstrip("=")

    return kodieren(privat), kodieren(oeffentlich)


def senden(abo, titel: str, text: str, url: str = "/dashboard") -> tuple[bool, str]:
    """
    Schickt eine Nachricht an ein Geraet.

    Gibt (geklappt, Meldung) zurueck. Ein 404 oder 410 vom Push-Dienst heisst
    "dieses Geraet gibt es nicht mehr" - dann wird das Abo geloescht, statt
    es weiter anzusprechen. Alles andere bleibt stehen: ein Netzproblem ist
    kein Grund, jemanden abzumelden.
    """
    from pywebpush import WebPushException, webpush

    from .models import MailSettings

    einstellungen = MailSettings.laden()
    if not einstellungen.push_ready:
        return False, "Push ist nicht eingerichtet."

    try:
        webpush(
            subscription_info={
                "endpoint": abo.endpoint,
                "keys": {"p256dh": abo.p256dh, "auth": abo.auth},
            },
            data=json.dumps({"title": titel, "body": text, "url": url}),
            vapid_private_key=einstellungen.vapid_private_key,
            vapid_claims={
                # Der Push-Dienst will wissen, wen er bei Missbrauch
                # erreichen kann. Ohne "sub" lehnen manche Dienste ab.
                "sub": f"mailto:{einstellungen.from_address or 'noreply@localhost'}",
            },
            timeout=getattr(settings, "PUSH_TIMEOUT", 10),
        )
        return True, ""
    except WebPushException as fehler:
        status = getattr(fehler.response, "status_code", None)
        if status in (404, 410):
            abo.delete()
            return False, "Gerät abgemeldet – Anmeldung entfernt."
        logger.warning("Push an %s fehlgeschlagen: %s", abo.endpoint[:60], fehler)
        return False, str(fehler)[:300]
    except Exception as fehler:  # noqa: BLE001
        logger.exception("Push fehlgeschlagen")
        return False, str(fehler)[:300]


def an_person(employee, titel: str, text: str, url: str = "/dashboard") -> int:
    """
    Schickt an alle Geraete einer Person. Gibt zurueck, wie viele erreicht
    wurden.

    Mehrere Geraete sind der Normalfall, nicht die Ausnahme: Diensthandy und
    privates Telefon, dazu der Rechner im Buero.
    """
    from .models import PushSubscription

    if employee is None or employee.user_id is None:
        return 0

    erreicht = 0
    for abo in PushSubscription.objects.filter(user_id=employee.user_id):
        geklappt, _ = senden(abo, titel, text, url)
        if geklappt:
            erreicht += 1
    return erreicht
