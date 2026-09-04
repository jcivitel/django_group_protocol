"""
Gesetzliche Feiertage.

Ohne sie rechnet die Software an drei Stellen falsch: die Monatssollstunden
zaehlen einen Feiertag als Arbeitstag, die Lohnuebergabe kennt keine
Feiertagsstunden, und im Dienstplan sieht der 3. Oktober aus wie ein
Dienstag. Das stand bisher als Kommentar in target_hours_for_month und war
die letzte offene Stelle, an der die Zeitrechnung nachweislich danebenlag.

Gerechnet statt gepflegt: Feiertage folgen einer Regel, und eine Liste, die
jedes Jahr jemand von Hand nachtragen muss, ist eine Liste, die irgendwann
fehlt. Die beweglichen Tage haengen alle am Ostersonntag, und der laesst
sich ausrechnen - die anderen stehen fest im Kalender.

Was die Rechnung nicht weiss, traegt die Verwaltung nach: Heiligabend und
Silvester sind vielerorts halbe Tage, manche Traeger geben Rosenmontag frei.
Deshalb ist das Ergebnis ein Vorschlag, den man bearbeiten kann, und keine
unveraenderliche Tabelle.
"""

from datetime import date, timedelta

# Die sechzehn Laender. Der Schluessel ist das uebliche Kfz-Kuerzel.
BUNDESLAENDER = [
    ("BW", "Baden-Württemberg"),
    ("BY", "Bayern"),
    ("BE", "Berlin"),
    ("BB", "Brandenburg"),
    ("HB", "Bremen"),
    ("HH", "Hamburg"),
    ("HE", "Hessen"),
    ("MV", "Mecklenburg-Vorpommern"),
    ("NI", "Niedersachsen"),
    ("NW", "Nordrhein-Westfalen"),
    ("RP", "Rheinland-Pfalz"),
    ("SL", "Saarland"),
    ("SN", "Sachsen"),
    ("ST", "Sachsen-Anhalt"),
    ("SH", "Schleswig-Holstein"),
    ("TH", "Thüringen"),
]

ALLE_LAENDER = {kuerzel for kuerzel, _ in BUNDESLAENDER}


def ostersonntag(jahr: int) -> date:
    """
    Ostersonntag nach der Gaussschen Osterformel (anonymer gregorianischer
    Algorithmus).

    Daran haengen Karfreitag, Ostermontag, Christi Himmelfahrt,
    Pfingstmontag und Fronleichnam - fuenf der neun beweglichen Tage.
    """
    a = jahr % 19
    b, c = divmod(jahr, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    monat, tag = divmod(h + l - 7 * m + 114, 31)
    return date(jahr, monat, tag + 1)


def busz_und_bettag(jahr: int) -> date:
    """Der Mittwoch vor dem 23. November - nur noch in Sachsen gesetzlich."""
    tag = date(jahr, 11, 23)
    # weekday(): Montag 0 ... Mittwoch 2
    return tag - timedelta(days=(tag.weekday() - 2) % 7 or 7)


def feiertage(jahr: int, land: str) -> list[tuple[date, str]]:
    """
    Die gesetzlichen Feiertage eines Jahres in einem Bundesland.

    Nicht enthalten sind die Tage, die nur in einzelnen Gemeinden gelten -
    Mariae Himmelfahrt in ueberwiegend katholischen bayerischen Gemeinden
    und Fronleichnam in Teilen Sachsens und Thueringens. Das haengt am Ort,
    nicht am Land; wer davon betroffen ist, traegt den Tag nach.
    """
    land = land.upper()
    ostern = ostersonntag(jahr)

    eintraege: list[tuple[date, str, set[str] | None]] = [
        # Feste Tage
        (date(jahr, 1, 1), "Neujahr", None),
        (date(jahr, 1, 6), "Heilige Drei Könige", {"BW", "BY", "ST"}),
        (date(jahr, 3, 8), "Internationaler Frauentag", {"BE", "MV"}),
        (date(jahr, 5, 1), "Tag der Arbeit", None),
        (date(jahr, 8, 8), "Augsburger Friedensfest", set()),  # nur Augsburg
        (date(jahr, 8, 15), "Mariä Himmelfahrt", {"SL"}),
        (date(jahr, 9, 20), "Weltkindertag", {"TH"}),
        (date(jahr, 10, 3), "Tag der Deutschen Einheit", None),
        (date(jahr, 10, 31), "Reformationstag", {"BB", "HB", "HH", "MV", "NI", "SN", "ST", "SH", "TH"}),
        (date(jahr, 11, 1), "Allerheiligen", {"BW", "BY", "NW", "RP", "SL"}),
        (date(jahr, 12, 25), "1. Weihnachtstag", None),
        (date(jahr, 12, 26), "2. Weihnachtstag", None),
        # Bewegliche Tage
        (ostern - timedelta(days=2), "Karfreitag", None),
        (ostern, "Ostersonntag", {"BB", "HE"}),
        (ostern + timedelta(days=1), "Ostermontag", None),
        (ostern + timedelta(days=39), "Christi Himmelfahrt", None),
        (ostern + timedelta(days=49), "Pfingstsonntag", {"BB", "HE"}),
        (ostern + timedelta(days=50), "Pfingstmontag", None),
        (ostern + timedelta(days=60), "Fronleichnam", {"BW", "BY", "HE", "NW", "RP", "SL"}),
        (busz_und_bettag(jahr), "Buß- und Bettag", {"SN"}),
    ]

    ergebnis = []
    for tag, name, laender in eintraege:
        if laender is None or land in laender:
            ergebnis.append((tag, name))
    return sorted(ergebnis)


# Tage, die kein gesetzlicher Feiertag sind, an denen aber vielerorts nur
# halb gearbeitet wird. Sie kommen als Vorschlag mit und lassen sich
# abwaehlen - verbindlich ist die Dienstvereinbarung des Traegers, nicht
# diese Datei.
HALBE_TAGE = [
    ((12, 24), "Heiligabend"),
    ((12, 31), "Silvester"),
]


def halbe_tage(jahr: int) -> list[tuple[date, str]]:
    return [(date(jahr, monat, tag), name) for (monat, tag), name in HALBE_TAGE]
