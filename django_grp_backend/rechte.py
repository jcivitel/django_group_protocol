"""
Eine Auskunftsstelle für jede Rechtefrage.

    darf(user, LESEN, protokoll)
    darf(user, DIENSTPLAN_FREIGEBEN, plan)

Vorher entschied `Employee.access_level` an gut dreissig Stellen, und die
Stufe galt für die ganze Anwendung. Wer den Dienstplan einer Gruppe freigeben
durfte, durfte auch das Tarifwerk des Trägers verstellen — es fehlte eine
Achse: **wo** gilt das Recht.

Dieses Modul ist Schritt 2 aus `rollenkonzept.md`. Es ändert zunächst nichts.
Es sammelt nur alle Entscheidungen an einer Stelle, damit der Umstieg auf
Rollen später eine Stelle ist und nicht vierzig.

## Die drei Betriebsarten

`RECHTE_QUELLE` in den Einstellungen entscheidet, wer antwortet:

    "stufe"     die Zugriffsstufe, wie bisher. Voreinstellung.
    "vergleich" die Stufe entscheidet, die Rollen rechnen mit. Weicht das
                Ergebnis ab, steht es im Protokoll — so sieht man vor dem
                Ernstfall, wem etwas fehlen würde.
    "rollen"    die Rollenzuweisungen entscheiden.

Der Weg über „vergleich" ist der Grund, warum diese Umstellung ohne einen
Tag Ausfall geht. Erst wenn eine Woche lang keine Abweichung mehr auffällt,
wird scharf geschaltet.

## Was hier nicht steht

Die Trennung nach Trägern. `limit_to_tenant()` bleibt die äusserste
Schranke. Rollen regeln, was jemand innerhalb seines Trägers darf — nicht,
welchen Träger er sieht.
"""

from __future__ import annotations

import logging

from django.conf import settings

from .access import ADMIN, ASSISTANT, SPECIALIST, access_level, employee_of

log = logging.getLogger("django_grp.rechte")


# ------------------------------------------------------------------ Aktionen
#
# Eine Zeile der Rechtematrix aus rollenkonzept.md, Abschnitt 4. Die Namen
# sind deutsch, weil sie in Fehlermeldungen und im Protokoll auftauchen.

ORG_STRUKTUR = "org.struktur"
ORG_DIENSTARTEN = "org.dienstarten"
ORG_KALENDER = "org.kalender"

PERSONAL_STAMMDATEN = "personal.stammdaten"
PERSONAL_ROLLEN = "personal.rollen"
PERSONAL_QUALIFIKATION = "personal.qualifikation"

DIENSTPLAN_BEARBEITEN = "dienst.plan"
DIENSTPLAN_FREIGEBEN = "dienst.freigabe"
ABWESENHEIT_GENEHMIGEN = "dienst.abwesenheit"
ZEIT_ERFASSEN = "zeit.erfassen"
ZEITKONTO_ABSCHLIESSEN = "zeit.abschluss"

PROTOKOLLE = "doku.protokolle"
BEWOHNER = "doku.bewohner"
FALLAKTE = "doku.fallakte"
FALLAKTE_GESCHUETZT = "doku.fallakte_geschuetzt"

AUSWERTUNG = "auswertung.kennzahlen"
NACHWEISE = "auswertung.nachweise"
AENDERUNGSPROTOKOLL = "auswertung.protokoll"


# ------------------------------------------------------------------- Stufen
KEIN = 0
LESEN = 1
SCHREIBEN = 2


# ---------------------------------------------------------------- Die Matrix
#
# Abschnitt 4 aus rollenkonzept.md, Zeile für Zeile. Was nicht eingetragen
# ist, gilt als KEIN: eine Rolle, die eine Ressource nicht kennt, darf sie
# nicht.
#
# Die Fussnoten der Tabelle stehen weiter unten in EINSCHRAENKUNG. Sie
# lassen sich hier nicht ausdrücken, weil sie nicht von der Rolle abhängen,
# sondern vom Gegenstand.

MATRIX: dict[str, dict[str, int]] = {
    "executive": {
        ORG_STRUKTUR: SCHREIBEN,
        ORG_DIENSTARTEN: SCHREIBEN,
        ORG_KALENDER: SCHREIBEN,
        PERSONAL_STAMMDATEN: SCHREIBEN,
        PERSONAL_ROLLEN: SCHREIBEN,
        PERSONAL_QUALIFIKATION: SCHREIBEN,
        DIENSTPLAN_BEARBEITEN: SCHREIBEN,
        DIENSTPLAN_FREIGEBEN: SCHREIBEN,
        ABWESENHEIT_GENEHMIGEN: SCHREIBEN,
        ZEIT_ERFASSEN: SCHREIBEN,
        ZEITKONTO_ABSCHLIESSEN: SCHREIBEN,
        PROTOKOLLE: LESEN,
        BEWOHNER: LESEN,
        FALLAKTE: LESEN,
        # Entschieden am 10. September 2026: die Leitung sieht auch
        # geschuetzte Vermerke. Der urspruengliche Vorschlag lautete anders.
        # Der Lesezugriff wandert dafuer ins Aenderungsprotokoll - nicht als
        # Sperre, sondern als Spur.
        FALLAKTE_GESCHUETZT: LESEN,
        AUSWERTUNG: SCHREIBEN,
        NACHWEISE: SCHREIBEN,
        AENDERUNGSPROTOKOLL: SCHREIBEN,
    },
    "facility_lead": {
        ORG_STRUKTUR: LESEN,
        ORG_DIENSTARTEN: SCHREIBEN,
        ORG_KALENDER: LESEN,
        PERSONAL_STAMMDATEN: SCHREIBEN,
        PERSONAL_ROLLEN: SCHREIBEN,
        PERSONAL_QUALIFIKATION: SCHREIBEN,
        DIENSTPLAN_BEARBEITEN: SCHREIBEN,
        DIENSTPLAN_FREIGEBEN: SCHREIBEN,
        ABWESENHEIT_GENEHMIGEN: SCHREIBEN,
        ZEIT_ERFASSEN: SCHREIBEN,
        ZEITKONTO_ABSCHLIESSEN: SCHREIBEN,
        PROTOKOLLE: LESEN,
        BEWOHNER: LESEN,
        FALLAKTE: LESEN,
        FALLAKTE_GESCHUETZT: LESEN,
        AUSWERTUNG: SCHREIBEN,
        NACHWEISE: SCHREIBEN,
        AENDERUNGSPROTOKOLL: SCHREIBEN,
    },
    "group_lead": {
        ORG_STRUKTUR: LESEN,
        ORG_DIENSTARTEN: LESEN,
        ORG_KALENDER: LESEN,
        PERSONAL_STAMMDATEN: LESEN,
        PERSONAL_QUALIFIKATION: LESEN,
        DIENSTPLAN_BEARBEITEN: SCHREIBEN,
        DIENSTPLAN_FREIGEBEN: SCHREIBEN,
        ABWESENHEIT_GENEHMIGEN: SCHREIBEN,
        ZEIT_ERFASSEN: SCHREIBEN,
        PROTOKOLLE: SCHREIBEN,
        BEWOHNER: SCHREIBEN,
        FALLAKTE: SCHREIBEN,
        AUSWERTUNG: SCHREIBEN,
        NACHWEISE: SCHREIBEN,
    },
    # Baut Plaene und pflegt Dienstarten - gibt aber nicht frei und sieht
    # keine Fachdokumentation. In groesseren Haeusern macht das eine
    # Planungskraft, nicht die Leitung.
    "duty_planner": {
        ORG_STRUKTUR: LESEN,
        ORG_DIENSTARTEN: SCHREIBEN,
        ORG_KALENDER: LESEN,
        PERSONAL_STAMMDATEN: LESEN,
        PERSONAL_QUALIFIKATION: LESEN,
        DIENSTPLAN_BEARBEITEN: SCHREIBEN,
        ABWESENHEIT_GENEHMIGEN: LESEN,
        ZEIT_ERFASSEN: SCHREIBEN,
        AUSWERTUNG: LESEN,
    },
    "specialist": {
        ORG_STRUKTUR: LESEN,
        ORG_DIENSTARTEN: LESEN,
        ORG_KALENDER: LESEN,
        PERSONAL_STAMMDATEN: LESEN,
        PERSONAL_QUALIFIKATION: LESEN,
        DIENSTPLAN_BEARBEITEN: LESEN,
        ZEIT_ERFASSEN: SCHREIBEN,
        PROTOKOLLE: SCHREIBEN,
        BEWOHNER: SCHREIBEN,
        FALLAKTE: SCHREIBEN,
        AUSWERTUNG: LESEN,
        NACHWEISE: LESEN,
    },
    "assistant": {
        ORG_STRUKTUR: LESEN,
        ORG_DIENSTARTEN: LESEN,
        ORG_KALENDER: LESEN,
        DIENSTPLAN_BEARBEITEN: LESEN,
        ZEIT_ERFASSEN: SCHREIBEN,
        PROTOKOLLE: LESEN,
        BEWOHNER: LESEN,
    },
    # Bezugsbetreuung. Der einzige Weg in die geschuetzte Tiefe einer Akte,
    # der nicht ueber die Leitung geht.
    "case_lead": {
        ORG_STRUKTUR: LESEN,
        PERSONAL_STAMMDATEN: LESEN,
        ZEIT_ERFASSEN: SCHREIBEN,
        PROTOKOLLE: SCHREIBEN,
        BEWOHNER: SCHREIBEN,
        FALLAKTE: SCHREIBEN,
        FALLAKTE_GESCHUETZT: SCHREIBEN,
        AUSWERTUNG: LESEN,
        NACHWEISE: SCHREIBEN,
    },
    # Personal- und Zeitdaten, ausdruecklich ohne paedagogische
    # Dokumentation. Heute haengt beides an derselben Stufe, und die
    # Lohnbuchhaltung sieht jedes Gruppenprotokoll.
    "administration": {
        ORG_STRUKTUR: LESEN,
        ORG_KALENDER: SCHREIBEN,
        PERSONAL_STAMMDATEN: SCHREIBEN,
        PERSONAL_QUALIFIKATION: SCHREIBEN,
        ZEIT_ERFASSEN: SCHREIBEN,
        ZEITKONTO_ABSCHLIESSEN: SCHREIBEN,
        AUSWERTUNG: SCHREIBEN,
    },
    # Jugendamt, Vormund, Therapie. Befristet, lesend, auf benannte Faelle.
    "external_reader": {
        BEWOHNER: LESEN,
        FALLAKTE: LESEN,
        NACHWEISE: LESEN,
    },
}

# Die Fussnoten der Matrix, soweit sie nicht schon aus dem Geltungsbereich
# folgen. Vier Augen ist keine Rechtefrage, sondern ein Freigabeschritt am
# Vorgang - er steht hier nur, damit die Stelle benannt ist.
EINSCHRAENKUNG = {
    ("group_lead", DIENSTPLAN_FREIGEBEN): "nur mit zweiter Freigabe",
    ("facility_lead", ZEITKONTO_ABSCHLIESSEN): "nur mit zweiter Freigabe",
    ("facility_lead", PERSONAL_ROLLEN): "nur Rollen unterhalb der eigenen",
    ("administration", AUSWERTUNG): "nur Personal und Zeit",
}


# ------------------------------------------------------ Was heute tatsaechlich gilt
#
# **Nicht dieselbe Tabelle wie MATRIX, und das ist der Punkt.** Wuerde die
# alte Stufe aus der neuen Matrix beantwortet, waeren beide Wege immer einig
# und die Betriebsart "vergleich" nutzlos. Hier steht deshalb, was die
# Anwendung heute tut - abgelesen an den Rechteklassen:
#
#   StaffWritableViewSet  Organisation und Personal aendern nur Mitarbeiter
#   WriteNeedsRole        alles Uebrige schreibt, wer keine Aushilfe ist
#
# Und: heute sieht jedes Gruppenmitglied die ganze Fallakte. Genau das ist
# die Zeile, die sich mit den Rollen aendern wird.

STUFE_RECHTE: dict[str, dict[str, int]] = {
    ADMIN: {aktion: SCHREIBEN for aktion in MATRIX["executive"]},
    SPECIALIST: {
        ORG_STRUKTUR: LESEN,
        ORG_DIENSTARTEN: SCHREIBEN,
        ORG_KALENDER: LESEN,
        PERSONAL_STAMMDATEN: LESEN,
        PERSONAL_QUALIFIKATION: LESEN,
        DIENSTPLAN_BEARBEITEN: SCHREIBEN,
        DIENSTPLAN_FREIGEBEN: SCHREIBEN,
        ABWESENHEIT_GENEHMIGEN: SCHREIBEN,
        ZEIT_ERFASSEN: SCHREIBEN,
        PROTOKOLLE: SCHREIBEN,
        BEWOHNER: SCHREIBEN,
        FALLAKTE: SCHREIBEN,
        FALLAKTE_GESCHUETZT: SCHREIBEN,
        AUSWERTUNG: LESEN,
        NACHWEISE: SCHREIBEN,
    },
    ASSISTANT: {
        ORG_STRUKTUR: LESEN,
        ORG_DIENSTARTEN: LESEN,
        ORG_KALENDER: LESEN,
        PERSONAL_STAMMDATEN: LESEN,
        PERSONAL_QUALIFIKATION: LESEN,
        DIENSTPLAN_BEARBEITEN: LESEN,
        ABWESENHEIT_GENEHMIGEN: LESEN,
        ZEIT_ERFASSEN: SCHREIBEN,
        PROTOKOLLE: LESEN,
        BEWOHNER: LESEN,
        FALLAKTE: LESEN,
        FALLAKTE_GESCHUETZT: LESEN,
        AUSWERTUNG: LESEN,
        NACHWEISE: LESEN,
    },
}


def _quelle() -> str:
    return getattr(settings, "RECHTE_QUELLE", "stufe")


# --------------------------------------------------------------- Geltungsbereich


def _bereich_von(objekt):
    """
    Auf welche Ebenen ein Gegenstand fällt.

    Gibt ein Wörterbuch mit den Nummern zurück, gegen die eine Rollenzuweisung
    prüfen kann: `{"department": 3, "facility": 1, ...}`. Was nicht bestimmbar
    ist, fehlt — und eine Rolle auf einer Ebene, die hier fehlt, greift dann
    nicht.

    `None` heisst: der Gegenstand hängt an keiner Stelle der Organisation.
    Dann entscheidet allein die Rolle, unabhängig davon, wo sie gilt.
    """
    if objekt is None:
        return None

    from django_grp_org.models import Department

    def bereich_zu_gruppe(group_id):
        if not group_id:
            return {}
        bereich = Department.objects.filter(group_id=group_id).first()
        if bereich is None:
            return {"group": group_id}
        return {
            "group": group_id,
            "department": bereich.id,
            "facility": bereich.facility_id,
            "site": bereich.facility.site_id,
        }

    name = objekt.__class__.__name__

    if name == "Group":
        return bereich_zu_gruppe(objekt.id)
    if name in ("Resident", "Protocol"):
        return bereich_zu_gruppe(objekt.group_id)
    if name == "CaseFile":
        ebenen = bereich_zu_gruppe(getattr(objekt.resident, "group_id", None))
        ebenen["case_file"] = objekt.id
        return ebenen
    if name == "Department":
        return {
            "department": objekt.id,
            "facility": objekt.facility_id,
            "site": objekt.facility.site_id,
        }
    if name == "Facility":
        return {"facility": objekt.id, "site": objekt.site_id}
    if name == "Site":
        return {"site": objekt.id}
    if name == "DutyPlan":
        return {
            "department": objekt.department_id,
            "facility": objekt.department.facility_id,
            "site": objekt.department.facility.site_id,
        }

    return None


def _rolle_deckt(rolle, ebenen) -> bool:
    """
    Deckt die Zuweisung den Gegenstand?

    Eine Rolle wirkt auf alles unterhalb ihrer Ebene. Trägerweit heisst
    überall; ein Bereich heisst nur dort. Ohne bestimmbare Ebenen zählt nur,
    dass die Rolle überhaupt gilt.
    """
    if rolle.scope_level == "S1":
        return True
    if ebenen is None:
        # Ohne Gegenstand ist die Frage nicht „wo", sondern „ueberhaupt".
        # Eine Gruppenleitung darf die Dienstarten lesen, ohne dass jemand
        # eine Gruppe dazu nennt - die Matrix allein entscheidet dann.
        #
        # Wer eine Entscheidung an einen Ort binden will, uebergibt den
        # Gegenstand. Das ist die Pflicht des Aufrufers und steht deshalb
        # in jedem Aufruf sichtbar.
        return True

    if rolle.case_file_id:
        return ebenen.get("case_file") == rolle.case_file_id
    if rolle.department_id:
        return ebenen.get("department") == rolle.department_id
    if rolle.facility_id:
        return ebenen.get("facility") == rolle.facility_id
    if rolle.site_id:
        return ebenen.get("site") == rolle.site_id
    return True


# ------------------------------------------------------------------ Die Antwort


def generalschluessel(user) -> bool:
    """
    Konten, die immer alles dürfen.

    Superuser und `is_staff`. Bewusst nicht abschaffbar: eine Rechteumstellung
    darf niemanden aussperren, der die Anlage betreut, und wer als
    Mitarbeitendes Konto gefuehrt wird, traegt ohnehin die Verantwortung fuer
    das Ganze.

    Praktisch ist das auch der Notausgang. Wer den Schalter auf `rollen`
    stellt und dabei eine Zuweisung vergisst, kommt ueber ein solches Konto
    wieder hinein - ohne Datenbankzugriff.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(
        getattr(user, "is_superuser", False) or getattr(user, "is_staff", False)
    )


def _aus_stufe(user, aktion, noetig) -> bool:
    """Wie bisher: eine Stufe, die für die ganze Anwendung gilt."""
    if generalschluessel(user):
        return True
    stufe = access_level(user)
    if stufe is None:
        return False
    return STUFE_RECHTE.get(stufe, {}).get(aktion, KEIN) >= noetig


def _aus_rollen(user, aktion, noetig, objekt) -> bool:
    """Aus den Rollenzuweisungen, die heute gelten."""
    if generalschluessel(user):
        return True

    employee = employee_of(user)
    if employee is None:
        return False

    ebenen = _bereich_von(objekt)
    for rolle in employee.roles.select_related(
        "facility", "department__facility"
    ):
        if not rolle.is_current():
            continue
        if MATRIX.get(rolle.role, {}).get(aktion, KEIN) < noetig:
            continue
        if _rolle_deckt(rolle, ebenen):
            return True
    return False


def darf(user, aktion: str, objekt=None, *, schreiben: bool = False) -> bool:
    """
    Darf diese Person diese Aktion an diesem Gegenstand?

    `schreiben=True` verlangt Schreibrecht, sonst genügt Lesen. Der
    Gegenstand bestimmt den Geltungsbereich; ohne ihn zählt allein die Rolle.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False

    noetig = SCHREIBEN if schreiben else LESEN
    quelle = _quelle()

    if quelle == "rollen":
        return _aus_rollen(user, aktion, noetig, objekt)

    antwort = _aus_stufe(user, aktion, noetig)

    if quelle == "vergleich":
        # Die Stufe entscheidet, die Rollen rechnen mit. Was auffaellt,
        # steht im Protokoll - vor dem Ernstfall und nicht danach.
        aus_rollen = _aus_rollen(user, aktion, noetig, objekt)
        if aus_rollen != antwort:
            log.warning(
                "Rechte weichen ab: %s %s %s – Stufe sagt %s, Rollen sagen %s",
                getattr(user, "username", "?"),
                aktion,
                "schreiben" if schreiben else "lesen",
                antwort,
                aus_rollen,
            )

    return antwort


def verwaltet(user) -> bool:
    """
    Darf diese Person die Anlage verwalten?

    Die Frage, die bisher `is_admin()` hiess und an gut zwanzig Stellen
    gestellt wird: Stammdaten aendern, Personal fuehren, Systemeinstellungen.
    Sie haengt an derselben Zeile der Matrix wie die Traegerstruktur.
    """
    return darf(user, ORG_STRUKTUR, schreiben=True)


def zweitfaktor_pflicht(user) -> bool:
    """
    Muss dieses Konto einen zweiten Faktor haben?

    Entschieden am 11. September 2026: freiwillig fuer alle, Pflicht fuer
    Konten, die verwalten duerfen. Das sind genau die, mit denen sich am
    meisten anrichten laesst - Personal, Organisation, Rollen.

    Die Regel haengt an derselben Zeile wie `verwaltet()`, und das ist die
    Kopplung, auf die es ankommt: es gibt keine Wiederherstellungscodes, die
    Verwaltung setzt den Faktor zurueck. Jedes Konto, das zuruecksetzen darf,
    ist damit ein Weg am Faktor vorbei. Waere die Pflicht anders geschnitten
    als das Recht zum Zuruecksetzen, bliebe genau dort eine Luecke.
    """
    return verwaltet(user)


def zweitfaktor_erfuellt(user) -> bool:
    """
    Ist die Pflicht erfuellt - oder besteht sie gar nicht?

    Getrennt von `zweitfaktor_pflicht()`, und das ist keine Umstaendlichkeit.
    Wuerde die Pflicht selbst davon abhaengen, ob ein Faktor aktiv ist, hoebe
    sie sich in dem Moment auf, in dem sie greifen soll: kein Faktor, also
    keine Verwaltungsrechte, also keine Pflicht. Die Pflicht haengt an den
    Rechten, die Erfuellung am Datensatz.

    Die Anmeldung selbst haelt das nicht auf. Wer verwalten darf und noch
    keinen Faktor hat, kommt hinein und arbeitet weiter - nur die
    Verwaltungsschreibzugriffe bleiben zu, bis er eingerichtet ist. Andersherum
    haette die Einfuehrung am ersten Tag die ganze Verwaltung ausgesperrt,
    und der erste Griff waere gewesen, die Pflicht wieder abzuschalten.
    """
    if not zweitfaktor_pflicht(user):
        return True

    from .models import ZweiterFaktor

    eintrag = ZweiterFaktor.objects.filter(user=user).first()
    return bool(eintrag and eintrag.ist_aktiv)


def schreibt_dokumentation(user, objekt=None) -> bool:
    """
    Darf diese Person fachlich dokumentieren?

    Die Frage hinter `WriteNeedsRole`: Protokolle, Bewohner, Fallakte. Eine
    Ergaenzungskraft darf das nicht, eine Fachkraft schon.
    """
    return darf(user, PROTOKOLLE, objekt, schreiben=True)


def rollen_von(user, stichtag=None) -> list:
    """
    Die heute geltenden Zuweisungen einer Person.

    Für die Oberfläche: wer wissen will, warum jemand etwas darf, soll die
    Zeilen sehen und nicht nur das Ergebnis.
    """
    employee = employee_of(user)
    if employee is None:
        return []
    return [
        rolle
        for rolle in employee.roles.select_related(
            "provider", "site", "facility", "department", "case_file"
        )
        if rolle.is_current(stichtag)
    ]
