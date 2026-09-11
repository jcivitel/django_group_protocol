"""
Der zweite Faktor: zeitbasierte Einmalcodes nach RFC 6238.

Warum das hier steht und nicht in einer Bibliothek: der Algorithmus ist
HMAC-SHA1 mit einer Zeitscheibe und einer abschliessenden Kuerzung, und er
ist in RFC 4226 und RFC 6238 so genau beschrieben, dass die offiziellen
Testvektoren eine vollstaendige Pruefung ergeben. Die stehen in
`tests_zweitfaktor.py`. Eine Abhaengigkeit mehr in einer Anwendung, die
Sozialdaten haelt, will begruendet sein; fuer dreissig Zeilen mit
Testvektoren aus dem Standard reicht die Begruendung nicht.

Was hier bewusst NICHT steht:

- **Kein Push.** Eine Freigabe per Push braucht das Telefon online, genau in
  dem Moment. Die Begleit-App ist fuer den Keller ohne Empfang gebaut; ein
  Code aus der Uhrzeit funktioniert dort weiter.
- **Keine Wiederherstellungscodes.** Entschieden am 11. September 2026: wer
  sein Telefon verliert, laesst den Faktor von der Verwaltung zuruecksetzen.
  Ein Zettel mit zehn Codes ist ein Zettel, der herumliegt.

Daraus folgt eine Kopplung, die kein Zufall ist: **wer zuruecksetzen darf,
muss selbst einen zweiten Faktor haben.** Sonst waere die Verwaltung der
stille Weg daran vorbei. Beide Regeln haengen an `rechte.verwaltet()`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

# Dreissig Sekunden je Scheibe und sechs Stellen - die Vorgabe aus RFC 6238
# und das, was jede Authenticator-App ohne Zusatzangabe erwartet. Ein eigener
# Takt waere mit der Begleit-App machbar und mit keiner anderen App.
SCHRITT = 30
STELLEN = 6

# Eine Scheibe Nachsicht in jede Richtung. Die Uhr eines Telefons weicht ab,
# und zwischen Ablesen und Tippen vergehen Sekunden. Zwei Scheiben waeren
# schon anderthalb Minuten, in denen ein abgelesener Code gilt.
TOLERANZ = 1

# 160 Bit, wie im Standard. In Base32 sind das 32 Zeichen - noch abtippbar,
# falls jemand den Schluessel von Hand in eine andere App traegt.
LAENGE_BYTES = 20


def geheimnis_erzeugen() -> str:
    """Ein neues Geheimnis als Base32, ohne Fuellzeichen."""
    return base64.b32encode(secrets.token_bytes(LAENGE_BYTES)).decode().rstrip("=")


def schritt_jetzt(zeitpunkt: float | None = None) -> int:
    """Die laufende Zeitscheibe."""
    return int((zeitpunkt if zeitpunkt is not None else time.time()) // SCHRITT)


def code(geheimnis: str, schritt: int) -> str:
    """
    Der Code einer Zeitscheibe.

    RFC 4226, Abschnitt 5.3: HMAC ueber den Zaehler, dann die dynamische
    Kuerzung. Das niederwertige Halbbyte des letzten Bytes zeigt auf die
    Stelle, ab der vier Bytes gelesen werden; das oberste Bit faellt weg,
    damit die Zahl auf jeder Plattform gleich vorzeichenlos ist.
    """
    schluessel = _entschluesseln_base32(geheimnis)
    abdruck = hmac.new(schluessel, struct.pack(">Q", schritt), hashlib.sha1).digest()

    versatz = abdruck[-1] & 0x0F
    ausschnitt = struct.unpack(">I", abdruck[versatz : versatz + 4])[0] & 0x7FFFFFFF

    return str(ausschnitt % (10**STELLEN)).zfill(STELLEN)


def pruefen(
    geheimnis: str,
    eingabe: str,
    zeitpunkt: float | None = None,
    zuletzt: int | None = None,
) -> int | None:
    """
    Prueft eine Eingabe und gibt die Zeitscheibe zurueck, die gepasst hat.

    `None` heisst: kein Treffer.

    `zuletzt` ist die Scheibe der letzten erfolgreichen Anmeldung. Wer sie
    mitgibt, verhindert die Wiederverwendung: ein Code, der einmal gegolten
    hat, gilt in denselben dreissig Sekunden nicht ein zweites Mal. Ohne
    diese Sperre koennte jemand, der einer Fachkraft ueber die Schulter
    sieht, sich direkt danach mit demselben Code anmelden.

    Verglichen wird in konstanter Zeit. Der Unterschied ist hier klein, aber
    er kostet auch nichts.
    """
    ziffern = "".join(z for z in (eingabe or "") if z.isdigit())
    if len(ziffern) != STELLEN:
        return None

    jetzt = schritt_jetzt(zeitpunkt)
    for versatz in range(-TOLERANZ, TOLERANZ + 1):
        kandidat = jetzt + versatz
        if zuletzt is not None and kandidat <= zuletzt:
            continue
        if hmac.compare_digest(code(geheimnis, kandidat), ziffern):
            return kandidat
    return None


def otpauth(geheimnis: str, konto: str, herausgeber: str) -> str:
    """
    Die Adresse, die in den QR-Code geht.

    Das Format stammt aus Google Authenticator und ist inzwischen das, was
    jede App liest. Der Herausgeber steht zweimal darin - einmal im Pfad und
    einmal als Feld -, weil aeltere Apps nur die eine Stelle lesen und
    neuere die andere.
    """
    beschriftung = quote(f"{herausgeber}:{konto}", safe="")
    felder = (
        f"secret={geheimnis}"
        f"&issuer={quote(herausgeber, safe='')}"
        f"&algorithm=SHA1&digits={STELLEN}&period={SCHRITT}"
    )
    return f"otpauth://totp/{beschriftung}?{felder}"


def _entschluesseln_base32(geheimnis: str) -> bytes:
    """
    Base32 ohne Ruecksicht auf Fuellzeichen und Kleinschreibung.

    Wer ein Geheimnis von Hand uebertraegt, tippt es klein und ohne die
    Gleichheitszeichen am Ende. Beides hier abzufangen ist billiger als eine
    Fehlermeldung, die niemand versteht.
    """
    sauber = (geheimnis or "").strip().replace(" ", "").upper()
    fehlend = (-len(sauber)) % 8
    return base64.b32decode(sauber + "=" * fehlend)
