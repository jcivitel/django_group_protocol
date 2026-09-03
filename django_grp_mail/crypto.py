"""
Das SMTP-Passwort verschluesselt ablegen.

Es steht in der Datenbank, weil die Einstellungen im Frontend gepflegt werden
sollen und nicht in einer .env. Im Klartext stuende es damit in jedem Backup
und in jedem Datenbank-Dump - auch in denen, die jemand zum Debuggen auf
seinen Rechner zieht.

Der Schluessel wird aus SECRET_KEY abgeleitet. Das ist kein Tresor: wer die
.env hat, kommt an das Passwort. Es haelt es aber aus Datenbank-Kopien
heraus, und genau die wandern erfahrungsgemaess herum.

Wird SECRET_KEY gewechselt, laesst sich das Passwort nicht mehr entschluesseln
- entschluesseln() gibt dann einen leeren String zurueck, und die Oberflaeche
verlangt eine Neueingabe. Das ist das richtige Verhalten: lieber einmal neu
eintippen als stillschweigend mit falschen Zugangsdaten weiterlaufen.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _schluessel() -> bytes:
    roh = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(roh)


def verschluesseln(klartext: str) -> str:
    if not klartext:
        return ""
    return Fernet(_schluessel()).encrypt(klartext.encode("utf-8")).decode("ascii")


def entschluesseln(geheim: str) -> str:
    if not geheim:
        return ""
    try:
        return Fernet(_schluessel()).decrypt(geheim.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""
