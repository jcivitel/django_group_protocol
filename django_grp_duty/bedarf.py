"""
Was ein Tag wirklich braucht.

Bisher legte der Generator je gewaehlter Dienstart einen Platz pro Tag an.
In einer Wohngruppe mit Tagdienst, 24-Stunden-Dienst und Nachtbereitschaft
sind das drei Plaetze taeglich - und damit rund 1440 Stunden im Monat, wo
sechs Mitarbeitende zusammen 860 vertraglich haben. Jeder Plan begann mit
einer Ueberlast, die keine Besetzung mehr auffangen konnte; am Ende stand
bei allen Ueberstunden.

Die Besetzungsvorgabe sagt aber gar nicht "alle Dienstarten". Sie sagt, wie
viele Menschen in einem Zeitfenster da sein muessen - hier: mindestens eine
Fachkraft von 10 bis 20 Uhr und mindestens eine von 20 bis 10 Uhr. Das
erfuellt ein 24-Stunden-Dienst allein, mit 23,5 Stunden. Tagdienst plus
Nachtbereitschaft erfuellen es auch, brauchen dafuer aber zwei Menschen und
24 Stunden.

Dieses Modul waehlt die guenstigste Kombination: die wenigsten Stunden, bei
Gleichstand die wenigsten Dienste. Es entscheidet nicht, WER arbeitet - das
macht der Automat in autofill.py -, sondern nur, WIE VIELE Plaetze welcher
Art ueberhaupt entstehen.

**Was hier bewusst nicht passiert.** Es wird nicht je Wochentag anders
gerechnet: die Besetzungsvorgabe kennt keine Wochentage, also kann auch
diese Rechnung keine kennen. Und es wird nicht ueber den Monat optimiert,
sondern ueber einen Tag - alle Tage sehen gleich aus, weil die Vorgabe fuer
alle gleich gilt.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import product

from .rules import DECKUNG_TOLERANZ_MINUTEN

TAG_MINUTEN = 24 * 60

# Wie gross der Suchraum hoechstens werden darf.
#
# Die Suche geht alle Kombinationen durch. Bei drei Dienstarten und einer
# geforderten Person sind das acht - nichts. Bei zwoelf Dienstarten und vier
# Personen waeren es fuenf Millionen, und dann dauert das Anlegen eines
# Monats laenger als die Geduld reicht. Darueber bleibt es bei einem Platz je
# Dienstart, so wie frueher: lieber die alte, verstaendliche Antwort als eine
# lange Rechnung, die niemand erwartet hat.
MAX_KOMBINATIONEN = 200_000


def _minuten(zeit) -> int:
    return zeit.hour * 60 + zeit.minute


def abschnitte(start, ende) -> list[tuple[int, int]]:
    """
    Welche Minuten eines Tages eine Spanne belegt - ein Stueck oder zwei.

    Ein Dienstplan wiederholt sich taeglich. Deshalb genuegt es, einen
    einzigen Tag zu betrachten: was nach Mitternacht laeuft, gehoert zum
    Anfang desselben Tages, nur eben aus dem Dienst des Vortages. Ein Dienst
    von 20:00 bis 10:30 belegt damit 20:00-24:00 und 00:00-10:30.
    """
    s, e = _minuten(start), _minuten(ende)
    if e > s:
        return [(s, e)]
    if e == s:
        # Exakt rund um die Uhr.
        return [(0, TAG_MINUTEN)]
    return [(s, TAG_MINUTEN), (0, e)]


def _ungedeckte_minuten(fenster, belegung: list[tuple[int, int, int]], mindest: int) -> int:
    """
    Wie viele Minuten des Fensters mit weniger als `mindest` Personen besetzt
    sind.

    `belegung` sind Abschnitte mit einer Anzahl: (von, bis, wie viele). Sie
    duerfen sich ueberlappen; gezaehlt wird die Summe.

    Gerechnet wird ueber Stuetzstellen und nicht Minute fuer Minute: die
    Anzahl aendert sich nur an den Raendern der Abschnitte, und davon gibt es
    eine Handvoll.
    """
    offen = 0
    for f_start, f_ende in fenster:
        punkte = {f_start, f_ende}
        for start, ende, _ in belegung:
            if f_start < start < f_ende:
                punkte.add(start)
            if f_start < ende < f_ende:
                punkte.add(ende)

        sortiert = sorted(punkte)
        for links, rechts in zip(sortiert, sortiert[1:]):
            mitte = (links + rechts) / 2
            anzahl = sum(
                wie_viele
                for start, ende, wie_viele in belegung
                if start <= mitte < ende
            )
            if anzahl < mindest:
                offen += rechts - links
    return offen


def erfuellt_vorgabe(vorgabe, anzahlen: dict[int, int], arten_nach_id: dict) -> bool:
    """Haelt diese Kombination diese eine Besetzungsvorgabe ein?"""
    if vorgabe.by_shift_type:
        return anzahlen.get(vorgabe.shift_type_id, 0) >= vorgabe.minimum_staff

    if not (vorgabe.starts_at and vorgabe.ends_at):
        return True

    belegung = [
        (start, ende, anzahl)
        for art_id, anzahl in anzahlen.items()
        if anzahl
        for start, ende in abschnitte(
            arten_nach_id[art_id].start_time, arten_nach_id[art_id].end_time
        )
    ]
    fenster = abschnitte(vorgabe.starts_at, vorgabe.ends_at)
    offen = _ungedeckte_minuten(fenster, belegung, vorgabe.minimum_staff)
    return offen <= DECKUNG_TOLERANZ_MINUTEN


def tagesbedarf(department, shift_types) -> dict[int, int]:
    """
    Wie viele Plaetze je Dienstart ein Tag braucht - so wenige wie moeglich.

    Gesucht wird die Kombination mit den wenigsten Stunden, die alle
    Besetzungsvorgaben des Bereichs einhaelt; bei gleichen Stunden die mit
    den wenigsten Diensten, weil jeder Dienst eine Person bindet.

    Gibt es fuer den Bereich keine einzige Vorgabe, bleibt es bei einem Platz
    je Dienstart. Das ist das alte Verhalten, und ohne Vorgabe gibt es auch
    nichts zu rechnen - der Bereich hat schlicht nicht gesagt, was er
    braucht.

    Laesst sich keine Kombination finden, die alles einhaelt, gilt dasselbe:
    lieber zu viele Plaetze, die jemand von Hand wegnimmt, als eine Luecke,
    die niemand bemerkt.
    """
    from .models import StaffingRequirement

    arten = list(shift_types)
    if not arten:
        return {}

    vorgaben = list(
        StaffingRequirement.objects.filter(department=department).select_related(
            "shift_type"
        )
    )
    if not vorgaben:
        return {art.id: 1 for art in arten}

    arten_nach_id = {art.id: art for art in arten}
    obergrenze = max(1, max(vorgabe.minimum_staff for vorgabe in vorgaben))

    if (obergrenze + 1) ** len(arten) > MAX_KOMBINATIONEN:
        return {art.id: 1 for art in arten}

    beste: dict[int, int] | None = None
    beste_bewertung: tuple[Decimal, int] | None = None

    for kombination in product(range(obergrenze + 1), repeat=len(arten)):
        anzahlen = {art.id: anzahl for art, anzahl in zip(arten, kombination)}
        if not any(anzahlen.values()):
            continue
        if not all(erfuellt_vorgabe(vorgabe, anzahlen, arten_nach_id) for vorgabe in vorgaben):
            continue

        stunden = sum(
            arten_nach_id[art_id].duration_hours * anzahl
            for art_id, anzahl in anzahlen.items()
            if anzahl
        )
        dienste = sum(anzahlen.values())
        bewertung = (stunden, dienste)

        if beste_bewertung is None or bewertung < beste_bewertung:
            beste, beste_bewertung = anzahlen, bewertung

    if beste is None:
        return {art.id: 1 for art in arten}
    return beste


def tagesstunden(bedarf: dict[int, int], shift_types) -> Decimal:
    """Wie viele Dienststunden ein Tag nach diesem Bedarf kostet."""
    arten_nach_id = {art.id: art for art in shift_types}
    return sum(
        (arten_nach_id[art_id].duration_hours * anzahl
         for art_id, anzahl in bedarf.items()
         if anzahl and art_id in arten_nach_id),
        Decimal("0"),
    )
