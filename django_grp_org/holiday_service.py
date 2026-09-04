"""
Feiertage anlegen und abfragen.

Getrennt von holidays.py: dort steht der Kalender als reine Rechnung, ohne
Datenbank. Hier wird daraus ein Bestand, den die Verwaltung bearbeiten kann.
"""

from datetime import date
from decimal import Decimal

from .holidays import feiertage, halbe_tage
from .models import Holiday


def jahr_anlegen(
    provider,
    jahr: int,
    land: str,
    *,
    mit_halben_tagen: bool = True,
) -> dict:
    """
    Legt die Feiertage eines Jahres an.

    Wiederholbar: was schon steht, bleibt unangetastet. Wer Heiligabend
    geloescht hat, weil im Haus durchgearbeitet wird, bekommt ihn beim
    naechsten Aufruf nicht zurueck - deshalb zaehlt der Rueckgabewert
    getrennt, was neu war und was schon da war.
    """
    vorhanden = set(
        Holiday.objects.filter(
            provider=provider, date__year=jahr
        ).values_list("date", flat=True)
    )

    neu = []
    for tag, name in feiertage(jahr, land):
        if tag in vorhanden:
            continue
        neu.append(
            Holiday(provider=provider, date=tag, name=name, factor=Decimal("0.00"))
        )

    if mit_halben_tagen:
        for tag, name in halbe_tage(jahr):
            if tag in vorhanden or any(eintrag.date == tag for eintrag in neu):
                continue
            neu.append(
                Holiday(
                    provider=provider,
                    date=tag,
                    name=name,
                    factor=Decimal("0.50"),
                    note="Kein gesetzlicher Feiertag – Vorschlag, bitte prüfen.",
                )
            )

    Holiday.objects.bulk_create(neu)
    return {
        "created": len(neu),
        "existing": len(vorhanden),
        "year": jahr,
        "state": land.upper(),
    }


def arbeitstage_im_monat(provider, jahr: int, monat: int) -> Decimal:
    """
    Werktage eines Monats, um Feiertage vermindert.

    Ein ganzer Feiertag zaehlt gar nicht, ein halber zur Haelfte. Feiertage,
    die auf ein Wochenende fallen, aendern nichts - sie waren ohnehin keine
    Arbeitstage, und wer sie abzoege, kuerzte das Soll zweimal.
    """
    import calendar

    tage_im_monat = calendar.monthrange(jahr, monat)[1]
    werktage = [
        date(jahr, monat, tag)
        for tag in range(1, tage_im_monat + 1)
        if date(jahr, monat, tag).weekday() < 5
    ]

    if provider is None:
        return Decimal(len(werktage))

    faktoren = dict(
        Holiday.objects.filter(
            provider=provider, date__year=jahr, date__month=monat
        ).values_list("date", "factor")
    )

    summe = Decimal("0")
    for tag in werktage:
        summe += faktoren.get(tag, Decimal("1"))
    return summe


def feiertage_im_zeitraum(provider, von: date, bis: date) -> dict:
    """Datum -> (Name, Faktor) fuer die Anzeige im Dienstplan."""
    if provider is None:
        return {}
    return {
        eintrag.date: (eintrag.name, eintrag.factor)
        for eintrag in Holiday.objects.filter(
            provider=provider, date__gte=von, date__lte=bis
        )
    }
