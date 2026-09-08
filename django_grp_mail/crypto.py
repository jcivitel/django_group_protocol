"""
Das SMTP-Passwort verschluesselt ablegen.

Es steht in der Datenbank, weil die Einstellungen im Frontend gepflegt werden
sollen und nicht in einer .env. Im Klartext stuende es damit in jedem Backup
und in jedem Datenbank-Dump - auch in denen, die jemand zum Debuggen auf
seinen Rechner zieht.

Woher der Schluessel kommt, in dieser Reihenfolge:

1. FIELD_ENCRYPTION_KEY, wenn gesetzt. Getrennt von SECRET_KEY, damit sich
   der eine drehen laesst, ohne den anderen zu entwerten - genau daran ist es
   frueher gescheitert: ein neuer SECRET_KEY hat die Mailkonfiguration
   stillschweigend unlesbar gemacht.
2. sonst abgeleitet aus SECRET_KEY, wie bisher.

Beim Entschluesseln werden zusaetzlich die Schluessel aus
SECRET_KEY_FALLBACKS probiert. So ueberlebt ein Schluesselwechsel die
bestehenden Werte: einmal lesen, einmal neu schreiben, fertig.

Das ist kein Tresor - wer die .env hat, kommt an das Passwort. Es haelt es
aber aus Datenbank-Kopien heraus, und genau die wandern erfahrungsgemaess
herum.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _ableiten(quelle: str) -> bytes:
    roh = hashlib.sha256(quelle.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(roh)


def _schluessel() -> bytes:
    """Der Schluessel, mit dem NEU verschluesselt wird."""
    eigener = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
    return _ableiten(eigener or settings.SECRET_KEY)


def _lese_schluessel() -> list[bytes]:
    """Alle Schluessel, mit denen ein vorhandener Wert entstanden sein kann."""
    quellen = []
    eigener = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
    if eigener:
        quellen.append(eigener)
    quellen.append(settings.SECRET_KEY)
    quellen.extend(getattr(settings, "SECRET_KEY_FALLBACKS", []) or [])

    gesehen = set()
    schluessel = []
    for quelle in quellen:
        if not quelle or quelle in gesehen:
            continue
        gesehen.add(quelle)
        schluessel.append(_ableiten(quelle))
    return schluessel


def verschluesseln(klartext: str) -> str:
    if not klartext:
        return ""
    return Fernet(_schluessel()).encrypt(klartext.encode("utf-8")).decode("ascii")


def entschluesseln(geheim: str) -> str:
    if not geheim:
        return ""
    roh = geheim.encode("ascii")
    for schluessel in _lese_schluessel():
        try:
            return Fernet(schluessel).decrypt(roh).decode("utf-8")
        except (InvalidToken, ValueError):
            continue
    # Kein Schluessel passt: leerer String, damit die Oberflaeche eine
    # Neueingabe verlangt, statt mit falschen Zugangsdaten weiterzulaufen.
    return ""
