"""
Volltextsuche über Protokolle, Verlauf und Bewohner.

## Wo die Leistung entschieden wird

Nicht am Index. Der ist schnell. Entschieden wird an drei Stellen:

**1. Erst die Sichtbarkeit, dann die Suche.** Die Gruppen des Kontos werden
einmal geholt und als Zahlenliste in die Abfrage gegeben. Damit prüft die
Datenbank `group_id IN (3, 7)` gegen einen Fremdschlüsselindex — statt über
eine Verbindungstabelle zu gehen, während sie zugleich einen Volltextindex
liest. Zwei Indizes in einer Abfrage nutzt kein Optimierer gut.

**2. Nicht die ganze Trefferliste sortieren.** Das war der teuerste Fehler,
und er ist gemessen: bei 48.000 Punkten kostet `MATCH` mit Gruppenfilter
17 ms — mit `ORDER BY protocol_date` sind es 64 ms. Der Grund ist, dass die
Datenbank für ein häufiges Wort erst alle zwölftausend Treffer holt, sie
sortiert und dann fünfundzwanzig behält.

Deshalb kommt ein **Fenster** aus der Datenbank: die `KANDIDATEN` besten nach
Relevanz, in der Reihenfolge, die der Volltextindex ohnehin liefert. Sortiert
wird danach in Python, über höchstens zweihundert Zeilen.

Was das kostet, gehört gesagt: bei einem sehr häufigen Wort sind es die
neuesten **unter den zweihundert treffendsten** und nicht die neuesten
überhaupt. Bei einem Wort, das ein paar Dutzend Mal vorkommt — und das ist
der Alltagsfall — ändert sich gar nichts.

**3. Ein Wort statt eines Satzes.** Wer drei Wörter eingibt, sucht nach allen
dreien. Im Boolean-Modus heißt das `+wort1* +wort2*` — der Stern, weil InnoDB
keine deutsche Wortstammbildung kennt und „Medikament" sonst
„Medikamentenplan" nicht findet.

## Wer was findet

Protokolle, Verlauf und Bewohner: jeder in seinen eigenen Gruppen.

**Personal nur für Verwaltungskonten.** Wer die Personalseite nicht öffnen
darf, soll Kolleginnen auch nicht über die Suche finden — sonst wäre die
Suche der bequeme Weg um eine Rechteprüfung herum. Gefragt wird dasselbe
wie auf der Seite selbst.

Personal wird auch dann durchsucht, wenn das Konto in keiner Gruppe ist.
Eine Personalabteilung hat keine Wohngruppe, und ohne diese Ausnahme fände
sie über die Suche gar nichts.

## Was die Suche nicht tut

Sie durchsucht keine Fallakten und keine geschützten Vermerke. Das ist keine
Lücke, sondern eine Entscheidung: eine Suche, die Treffer aus Akten anzeigt,
die man in der Liste nicht sehen darf, ist eine Umgehung der Rechte mit
Komfortbegründung. Wenn Fallakten dazukommen sollen, gehören sie über
`accessible_case_files()` gefiltert und nicht über die Gruppenzugehörigkeit.

## Wenn der Index fehlt

`MATCH ... AGAINST` braucht den Volltextindex; ohne ihn wirft MariaDB einen
Fehler. Dann fällt jede Abfrage auf `LIKE` zurück — richtig, aber ohne Index
und damit langsam. Das steht im Protokoll, damit es auffällt.
"""

from __future__ import annotations

import logging
import re

from django.db import OperationalError, ProgrammingError, connection
from django.db.models import Q

from .access import employee_of  # noqa: F401  (haelt die Abhaengigkeit sichtbar)
from .rechte import verwaltet

log = logging.getLogger("django_grp.suche")

# So viele Treffer je Quelle. Wer mehr braucht, sucht genauer - eine Liste
# mit dreihundert Zeilen liest niemand.
GRENZE = 25

# So viele Zeilen holt die Datenbank, bevor in Python nach Datum sortiert
# wird. Achtmal die Grenze: genug, dass bei einem gewoehnlichen Suchwort
# alles dabei ist, und wenig genug, dass die Sortierung nichts kostet.
KANDIDATEN = 200

# Kuerzer sucht InnoDB nicht (innodb_ft_min_token_size, ab Werk drei). Statt
# einer leeren Liste sagt die Suche das vorher.
MINDESTLAENGE = 3

# Alles, was kein Wortzeichen ist, fliegt raus. Im Boolean-Modus sind +, -,
# *, ", ( und ) Steuerzeichen; ein Suchwort mit Klammer waere sonst ein
# Syntaxfehler in der Datenbank und keine leere Ergebnisliste.
NUR_WORT = re.compile(r"[^\w\-]+", re.UNICODE)


def begriffe(suchtext: str) -> list[str]:
    """Die brauchbaren Wörter einer Eingabe."""
    roh = NUR_WORT.sub(" ", suchtext or "").split()
    return [wort for wort in roh if len(wort) >= MINDESTLAENGE]


def boolean_ausdruck(woerter: list[str]) -> str:
    """
    Der Ausdruck für den Boolean-Modus.

    `+wort*` je Wort: alle müssen vorkommen, jedes darf vorne stehen. Das
    trifft die deutsche Beugung und die zusammengesetzten Wörter, an denen
    eine Suche ohne Wortstammbildung sonst scheitert.
    """
    return " ".join(f"+{wort}*" for wort in woerter)


class Treffer:
    """Eine Zeile im Ergebnis, unabhängig davon, woher sie kommt."""

    __slots__ = ("art", "id", "titel", "unterzeile", "ausschnitt", "datum", "pfad")

    def __init__(self, art, id, titel, unterzeile, ausschnitt, datum, pfad):
        self.art = art
        self.id = id
        self.titel = titel
        self.unterzeile = unterzeile
        self.ausschnitt = ausschnitt
        self.datum = datum
        self.pfad = pfad


def _sichtbare_gruppen(user) -> list[int]:
    """
    Die Gruppennummern, die dieses Konto sehen darf.

    Eine kleine Abfrage, deren Ergebnis in jede folgende als Zahlenliste
    eingeht. Genau darum geht es: die Datenbank soll `group_id IN (…)` gegen
    einen Fremdschlüsselindex prüfen und nicht nebenher eine
    Verbindungstabelle lesen.
    """
    from .models import Group

    return list(Group.objects.for_user(user).values_list("id", flat=True))


def _ausschnitt(text: str, woerter: list[str], laenge: int = 180) -> str:
    """Der Satz um den ersten Treffer, nicht der ganze Text."""
    if not text:
        return ""
    klein = text.lower()
    stelle = min(
        (klein.find(wort.lower()) for wort in woerter if wort.lower() in klein),
        default=-1,
    )
    if stelle == -1:
        return " ".join(text[:laenge].split())

    halb = laenge // 2
    von = max(0, stelle - halb)
    bis = min(len(text), stelle + halb)
    kern = " ".join(text[von:bis].split())
    return f"{'… ' if von > 0 else ''}{kern}{' …' if bis < len(text) else ''}"


def _volltext(queryset, spalte: str, ausdruck: str, woerter: list[str], nach):
    """
    `MATCH … AGAINST`, ein Fenster, und dann erst sortieren.

    `queryset` kommt **ohne** `order_by`. Das ist der Punkt: der Volltextindex
    liefert die treffendsten Zeilen zuerst, und wer eine Sortierung
    danebenstellt, zwingt die Datenbank, alles zu holen und zu ordnen.

    `nach` sagt, wonach die geholten Zeilen in Python sortiert werden —
    in aller Regel das Datum, denn im Alltag sucht niemand das treffendste
    Protokoll, sondern das letzte.

    Der Rückfall auf `LIKE` ist bewusst kein stiller: eine Suche, die ohne
    Index im Schneckengang läuft, sucht nach einem halben Jahr jemand
    stundenlang.
    """
    if connection.vendor != "mysql":
        zeilen = list(_wie_like(queryset, spalte, woerter)[:KANDIDATEN])
    else:
        versuch = queryset.extra(  # noqa: S610 - Parameter sind gebunden
            where=[f"MATCH({spalte}) AGAINST (%s IN BOOLEAN MODE)"],
            params=[ausdruck],
        )
        try:
            # Erzwingt die Auswertung, damit ein fehlender Index hier
            # auffaellt und nicht erst beim Zusammensetzen der Antwort.
            zeilen = list(versuch[:KANDIDATEN])
        except (OperationalError, ProgrammingError) as fehler:
            log.warning(
                "Volltextindex auf %s fehlt (%s) - die Suche laeuft ueber LIKE.",
                spalte,
                fehler,
            )
            zeilen = list(_wie_like(queryset, spalte, woerter)[:KANDIDATEN])

    zeilen.sort(key=nach, reverse=True)
    return zeilen[:GRENZE]


def _wie_like(queryset, spalte: str, woerter: list[str]):
    """Ohne Index: jedes Wort muss vorkommen."""
    feld = spalte.split(".")[-1].strip("`")
    bedingung = Q()
    for wort in woerter:
        bedingung &= Q(**{f"{feld}__icontains": wort})
    return queryset.filter(bedingung)


def _personal(user, woerter: list[str]) -> list:
    """
    Personaldatensätze, wenn das Konto sie ohnehin sehen darf.

    Nach Namensanfang und Personalnummer, nicht über den Volltextindex:
    Namen sind kurz, und „and" soll nicht jeden zweiten Nachnamen finden.

    **Gefragt wird `verwaltet()` und nicht das Leserecht am Endpunkt.** Der
    Endpunkt `/api/v1/employee/` lässt jeden Angemeldeten lesen, weil der
    Dienstplan die Namen der Kolleginnen braucht. Die Personalseite selbst
    steht aber nur der Verwaltung offen. Träfe die Suche die weitere Regel,
    böte sie einer Fachkraft Treffer an, deren Link auf eine Seite führt,
    die sie nicht öffnen darf — und zeigte dabei Zugriffsstufe und
    Personalnummer.
    """
    if not verwaltet(user):
        return []

    from django_grp_org.models import Employee
    from django_grp_org.tenancy import limit_to_tenant

    namen = Q()
    for wort in woerter:
        namen |= (
            Q(first_name__istartswith=wort)
            | Q(last_name__istartswith=wort)
            | Q(personnel_number__istartswith=wort)
        )

    return [
        Treffer(
            art="personal",
            id=person.id,
            titel=person.get_full_name(),
            unterzeile=(
                person.get_access_level_display()
                + (" · ausgeschieden" if person.left_on else "")
            ),
            ausschnitt="",
            datum=person.hired_on,
            pfad=f"/personal?person={person.id}",
        )
        for person in limit_to_tenant(
            Employee.objects.filter(namen), user
        ).order_by("last_name", "first_name")[:GRENZE]
    ]


def suchen(user, suchtext: str) -> dict:
    """
    Sucht in Protokollen, Verlauf und Bewohnern der eigenen Gruppen.

    Gibt ein Wörterbuch mit den drei Gruppen zurück, damit die Oberfläche sie
    getrennt zeigen kann. Eine Liste, in der ein Bewohner zwischen zwei
    Protokollzeilen steht, liest sich schlechter als drei kurze.
    """
    from .models import Protocol, ProtocolItem, ProtocolObservation, Resident

    woerter = begriffe(suchtext)
    if not woerter:
        return {
            "begriffe": [],
            "hinweis": (
                f"Bitte mindestens {MINDESTLAENGE} Buchstaben eingeben."
                if (suchtext or "").strip()
                else ""
            ),
            "protokolle": [],
            "verlauf": [],
            "bewohner": [],
            "personal": [],
        }

    # Personal haengt nicht an Gruppen: eine Personalabteilung hat keine
    # Wohngruppe und faende sonst gar nichts.
    personal = _personal(user, woerter)

    gruppen = _sichtbare_gruppen(user)
    if not gruppen:
        return {
            "begriffe": woerter,
            "hinweis": "",
            "protokolle": [],
            "verlauf": [],
            "bewohner": [],
            "personal": personal,
        }

    ausdruck = boolean_ausdruck(woerter)

    # ------------------------------------------------------------ Protokolle
    punkte = _volltext(
        ProtocolItem.objects.filter(protocol__group_id__in=gruppen)
        .select_related("protocol", "protocol__group")
        .order_by(),
        "`django_grp_backend_protocolitem`.`value`",
        ausdruck,
        woerter,
        nach=lambda punkt: (punkt.protocol.protocol_date, punkt.protocol_id),
    )

    themen = _volltext(
        Protocol.objects.filter(group_id__in=gruppen)
        .select_related("group")
        .order_by(),
        "`django_grp_backend_protocol`.`topic`",
        ausdruck,
        woerter,
        nach=lambda protokoll: (protokoll.protocol_date, protokoll.id),
    )

    protokolle = [
        Treffer(
            art="protokoll",
            id=punkt.protocol_id,
            titel=punkt.name or "Protokoll",
            unterzeile=f"{punkt.protocol.group.name} · {punkt.protocol.protocol_date:%d.%m.%Y}",
            ausschnitt=_ausschnitt(punkt.value or "", woerter),
            datum=punkt.protocol.protocol_date,
            pfad=f"/protokolle/{punkt.protocol_id}",
        )
        for punkt in punkte
    ]
    # Ein Thema, dessen Protokoll schon ueber einen Punkt gefunden wurde,
    # kommt nicht zweimal.
    schon_da = {treffer.id for treffer in protokolle}
    protokolle += [
        Treffer(
            art="protokoll",
            id=protokoll.id,
            titel=protokoll.topic or "Protokoll",
            unterzeile=f"{protokoll.group.name} · {protokoll.protocol_date:%d.%m.%Y}",
            ausschnitt="",
            datum=protokoll.protocol_date,
            pfad=f"/protokolle/{protokoll.id}",
        )
        for protokoll in themen
        if protokoll.id not in schon_da
    ]

    # --------------------------------------------------------------- Verlauf
    eintraege = _volltext(
        ProtocolObservation.objects.filter(protocol__group_id__in=gruppen)
        .select_related("protocol", "protocol__group", "resident")
        .order_by(),
        "`django_grp_backend_protocolobservation`.`text`",
        ausdruck,
        woerter,
        nach=lambda eintrag: (eintrag.protocol.protocol_date, eintrag.id),
    )
    verlauf = [
        Treffer(
            art="verlauf",
            id=eintrag.id,
            titel=(
                eintrag.resident.get_full_name()
                if eintrag.resident_id
                else eintrag.protocol.group.name
            ),
            unterzeile=f"{eintrag.get_category_display()} · {eintrag.protocol.protocol_date:%d.%m.%Y}",
            ausschnitt=_ausschnitt(eintrag.text or "", woerter),
            datum=eintrag.protocol.protocol_date,
            pfad=(
                f"/bewohner/{eintrag.resident_id}"
                if eintrag.resident_id
                else f"/protokolle/{eintrag.protocol_id}"
            ),
        )
        for eintrag in eintraege
    ]

    # -------------------------------------------------------------- Bewohner
    #
    # Namen sind kurz, und ein Volltextindex ueber zwei Woerter bringt nichts
    # gegenueber einem gewoehnlichen Praefixvergleich. Gesucht wird nach
    # Anfang, nicht irgendwo im Wort: "Neu" soll Nele Neumann finden, aber
    # nicht jeden, in dessen Namen die drei Buchstaben vorkommen.
    namen = Q()
    for wort in woerter:
        namen |= Q(first_name__istartswith=wort) | Q(last_name__istartswith=wort)

    bewohner = [
        Treffer(
            art="bewohner",
            id=person.id,
            titel=person.get_full_name(),
            unterzeile=(
                f"{person.group.name}"
                + (" · ausgezogen" if person.moved_out_since else "")
            ),
            ausschnitt="",
            datum=person.moved_in_since,
            pfad=f"/bewohner/{person.id}",
        )
        for person in Resident.objects.filter(namen, group_id__in=gruppen)
        .select_related("group")
        .order_by("last_name", "first_name")[:GRENZE]
    ]

    return {
        "begriffe": woerter,
        "hinweis": "",
        "protokolle": protokolle[:GRENZE],
        "verlauf": verlauf,
        "bewohner": bewohner,
        "personal": personal,
    }
