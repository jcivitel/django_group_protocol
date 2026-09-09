"""
Automatische Dienstbesetzung.

Der Automat nimmt einem die stumpfe Arbeit ab, nicht die Entscheidung. Er
besetzt offene Dienste der Reihe nach mit der Person, die gerade am besten
passt, und legt offen, warum er wen genommen hat. Was er nicht besetzen kann,
laesst er offen stehen - lieber eine sichtbare Luecke als eine stille
Fehlbesetzung.

Wonach er geht, in dieser Reihenfolge:

1. **Was nicht geht, geht nicht.** Abwesenheit, ein zweiter Dienst am selben
   Tag, weniger als elf Stunden Ruhezeit, "nicht verfuegbar" als Wunsch -
   das sind harte Ausschluesse, nicht Abzuege.
2. **Wer noch Stunden offen hat, kommt zuerst.** Das Arbeitszeitmodell gibt
   das Monatssoll vor; wer prozentual am weitesten darunter liegt, bekommt
   den Dienst. Ohne dieses Gewicht arbeiten dieselben drei Leute den Monat.
3. **Wuensche zaehlen.** Ein Wunsch zieht kraeftig, ein "moechte nicht"
   drueckt - aber keines von beidem ist bindend, so wie es die Oberflaeche
   auch sagt.
4. **Fachkraftquote.** Verlangt die Besetzungsvorgabe Fachkraefte, werden
   deren Plaetze zuerst mit Fachkraeften besetzt.
5. **Wochenenden gleichmaessig.** Wer schon zwei Wochenendtage hat, bekommt
   den dritten erst, wenn niemand sonst kann.

Kein Optimierungsverfahren, sondern ein gieriger Durchlauf: Dienst fuer
Dienst, in zeitlicher Reihenfolge. Das ist nachvollziehbar - man kann jede
einzelne Entscheidung erklaeren - und fuer einen Monat einer Wohngruppe
schnell genug. Ein Loeser, der das Optimum findet, waere hier nicht besser,
sondern nur schwerer zu verstehen, wenn er etwas tut, das niemand erwartet.
"""

from collections import defaultdict
from itertools import combinations
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django_grp_org.models import Employee

from .models import Absence, Shift, ShiftPreference, StaffingRequirement
from .rules import MAX_CONSECUTIVE_DAYS, MIN_REST_HOURS, serie_um
from .services import ruhezeit, target_hours_for_month

# Wie weit ueber das Monatssoll hinaus noch eingeteilt wird, bevor jemand
# als "voll" gilt. Etwas Luft muss sein, sonst bleibt der letzte Dienst im
# Monat offen, obwohl jemand ihn ohne Weiteres uebernehmen koennte.
UEBERSTUNDEN_TOLERANZ = Decimal("1.10")

# Gewichte. Absolute Zahlen sind egal, es zaehlt das Verhaeltnis.
GEWICHT_STUNDENLUECKE = 100  # je Anteil des noch offenen Solls
GEWICHT_WUNSCH = 60
ABZUG_MOECHTE_NICHT = 45
GEWICHT_FACHKRAFT = 25
ABZUG_JE_WOCHENENDTAG = 12
ABZUG_UEBER_SOLL = 80
# Kein Ausschluss, nur ein Vorzug: "zaehlt fuer die Fachkraftquote" heisst
# nicht "nur Fachkraefte duerfen das". Als Abzug in der Groessenordnung der
# Stundenluecke gelesen, drueckte das jede Nicht-Fachkraft auf null Dienste -
# in einem Team von acht bekamen zwei den ganzen Monat nichts.
VORZUG_QUOTENDIENST = 10


@dataclass
class Zuteilung:
    """Eine Entscheidung des Automaten, zum Nachlesen."""

    shift_id: int
    date: str
    shift_type: str
    employee_id: int
    employee_name: str
    reason: str


@dataclass
class Bilanz:
    """Was der Durchlauf bewirkt hat."""

    assigned: list[Zuteilung] = field(default_factory=list)
    still_open: int = 0
    cleared: int = 0
    hours: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "assigned": [zuteilung.__dict__ for zuteilung in self.assigned],
            "assigned_count": len(self.assigned),
            "still_open": self.still_open,
            "cleared": self.cleared,
            "hours": self.hours,
            "notes": self.notes,
        }


def mitarbeitende(department) -> list[Employee]:
    """
    Wer in diesem Bereich arbeitet.

    Zwei Wege, wie in der Vertretungssuche: eine Stellenbesetzung im Bereich
    oder Mitgliedschaft in der Gruppe, die am Bereich haengt. Der Stellplan
    wird in vielen Haeusern nicht gepflegt, die Gruppenzuordnung dagegen
    immer.
    """
    provider = department.facility.site.provider
    alle = (
        Employee.objects.filter(provider=provider, left_on__isnull=True)
        .select_related("work_time_model")
        .prefetch_related("qualifications", "assignments__position")
    )

    gruppenmitglieder = set()
    if department.group_id:
        gruppenmitglieder = set(
            department.group.group_members.values_list("id", flat=True)
        )

    drin = []
    for person in alle:
        eigen = any(
            zuweisung.position.department_id == department.id
            for zuweisung in person.assignments.all()
        )
        if not eigen and person.user_id in gruppenmitglieder:
            eigen = True
        if eigen:
            drin.append(person)
    return drin


def konto_stunden(shift_type) -> Decimal:
    """
    Was ein Dienst auf dem Zeitkonto wiegt.

    Bereitschaft zaehlt zur Haelfte - dieselbe Rechnung wie bei der
    Zeitbuchung, sonst sieht ein 24-Stunden-Dienst hier nach 24 Stunden aus
    und die Person waere nach zwei Diensten "voll".
    """
    arbeit = shift_type.work_hours
    bereitschaft = shift_type.on_call_hours
    return (arbeit + bereitschaft * Decimal("0.5")).quantize(Decimal("0.01"))


def _fachkraftbedarf(department) -> dict[int, int]:
    """Wie viele Fachkraefte je Dienstart vorgeschrieben sind."""
    return {
        eintrag.shift_type_id: eintrag.minimum_specialists
        for eintrag in StaffingRequirement.objects.filter(
            department=department, shift_type__isnull=False
        )
    }


def autofill_plan(plan, *, overwrite: bool = False) -> dict:
    """
    Besetzt die offenen Dienste eines Plans.

    Mit `overwrite` werden vorhandene Besetzungen zuerst geloescht und der
    ganze Monat neu verteilt - fuer den Fall, dass sich die Belegschaft oder
    die Vorgaben geaendert haben. Ohne das bleibt jede Handeinteilung stehen;
    der Automat fuellt nur auf.
    """
    bilanz = Bilanz()
    department = plan.department

    personen = mitarbeitende(department)
    if not personen:
        bilanz.notes.append(
            "Diesem Bereich ist niemand zugeordnet – weder über eine Stelle "
            "noch über die Gruppe. Ohne Personal lässt sich nichts planen."
        )
        bilanz.still_open = plan.shifts.filter(employee__isnull=True).count()
        return bilanz.as_dict()

    if overwrite:
        bilanz.cleared = plan.shifts.filter(employee__isnull=False).update(
            employee=None, is_substitute=False
        )

    dienste = list(
        plan.shifts.select_related("shift_type")
        .order_by("date", "shift_type__start_time", "id")
    )
    offen = [dienst for dienst in dienste if dienst.employee_id is None]
    if not offen:
        bilanz.notes.append("Es war kein Dienst offen.")
        return bilanz.as_dict()

    tage = [dienst.date for dienst in dienste]
    von, bis = min(tage), max(tage)

    # --- Alles einmal vorladen. Der Automat fragt sonst je Dienst und Person
    # nach, und das sind bei 90 Diensten und 8 Personen 720 Abfragen.

    abwesend: dict[int, set] = defaultdict(set)
    for absence in Absence.objects.filter(
        status="approved", start_date__lte=bis, end_date__gte=von
    ):
        tag = absence.start_date
        while tag <= absence.end_date:
            abwesend[absence.employee_id].add(tag)
            tag += timedelta(days=1)

    wuensche: dict[tuple, str] = {}
    for wunsch in ShiftPreference.objects.filter(date__gte=von, date__lte=bis):
        # Ein Wunsch fuer den ganzen Tag (ohne Dienstart) gilt fuer jeden
        # Dienst des Tages - deshalb zwei Schluessel.
        wuensche[(wunsch.employee_id, wunsch.date, wunsch.shift_type_id)] = wunsch.kind

    fachkraftbedarf = _fachkraftbedarf(department)
    ist_fachkraft = {person.id: person.is_specialist for person in personen}

    # Belegung, waehrend der Durchlauf laeuft. Auch Dienste ausserhalb dieses
    # Plans zaehlen mit: wer im Nachbarbereich Nachtdienst hat, kann hier
    # nicht gleichzeitig stehen.
    #
    # Das Fenster reicht so weit, wie eine Serie lang sein darf. Mit einem
    # Tag Rand - so war es - sieht der Automat die Ruhezeit, aber nicht, dass
    # jemand die letzten sechs Tage des Vormonats schon durchgearbeitet hat.
    rand = timedelta(days=MAX_CONSECUTIVE_DAYS)
    belegt: dict[int, list] = defaultdict(list)
    for fremd in (
        Shift.objects.filter(
            date__gte=von - rand,
            date__lte=bis + rand,
            employee__isnull=False,
        )
        .select_related("shift_type")
    ):
        belegt[fremd.employee_id].append(fremd)

    # Stundenkonto: Soll aus dem Arbeitszeitmodell, Ist aus dem, was schon
    # steht.
    soll: dict[int, Decimal] = {}
    ist: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for person in personen:
        soll[person.id] = target_hours_for_month(person, plan.year, plan.month)
    for dienst in dienste:
        if dienst.employee_id in soll:
            ist[dienst.employee_id] += konto_stunden(dienst.shift_type)

    wochenendtage: dict[int, int] = defaultdict(int)
    for dienst in dienste:
        if dienst.employee_id and dienst.date.weekday() >= 5:
            wochenendtage[dienst.employee_id] += 1

    # --- Der eigentliche Durchlauf, Tag fuer Tag.
    #
    # Frueher lief er Dienst fuer Dienst und besetzte jeden. Das war die
    # falsche Frage: der Plan haelt je Dienstart einen Platz bereit, aber
    # nicht jeder davon wird an jedem Tag gebraucht. Wer stur alle besetzt,
    # verplant bei Tagdienst, 24-Stunden-Dienst und Nachtbereitschaft rund
    # 1240 Stunden im Monat, wo das Team 1200 hat - und am Monatsende haben
    # alle Ueberstunden, gleich wie geschickt verteilt wurde.
    #
    # Jetzt entscheidet er je Tag, WELCHE Plaetze er besetzt. Dazu probiert
    # er die moeglichen Kombinationen durch und nimmt die, die dem Team am
    # meisten fehlende Stunden bringt, ohne jemanden ueber sein Soll zu
    # schieben. Am einen Tag sind das Tag und Nacht, am naechsten der
    # 24-Stunden-Dienst allein, am dritten Tag plus 24er - was gerade passt.
    #
    # Bedingung bleibt die Besetzungsvorgabe: was sie verlangt, muss gedeckt
    # sein. Sie ist ein Mindestmass, keine Obergrenze - darueber hinaus darf
    # besetzt werden, wenn es jemandem Stunden bringt.

    fachkraefte_gesetzt: dict[tuple, int] = defaultdict(int)
    for dienst in dienste:
        if dienst.employee_id and ist_fachkraft.get(dienst.employee_id):
            fachkraefte_gesetzt[(dienst.date, dienst.shift_type_id)] += 1

    vorgaben = list(
        StaffingRequirement.objects.filter(department=department).select_related(
            "shift_type"
        )
    )
    arten_nach_id = {
        dienst.shift_type_id: dienst.shift_type for dienst in dienste
    }

    nach_tag: dict = defaultdict(list)
    for dienst in dienste:
        nach_tag[dienst.date].append(dienst)

    alle_tage = sorted(nach_tag)
    for nummer, tag in enumerate(alle_tage, start=1):
        # Wie viel des Monatssolls bis zu diesem Tag faellig waere.
        tempo = Decimal(nummer) / Decimal(len(alle_tage))
        des_tages = nach_tag[tag]
        besetzt = [d for d in des_tages if d.employee_id is not None]
        frei = [d for d in des_tages if d.employee_id is None]
        if not frei:
            continue

        zustand = _Zustand(
            belegt=belegt,
            ist=ist,
            wochenendtage=wochenendtage,
            fachkraefte_gesetzt=fachkraefte_gesetzt,
        )

        beste = _beste_kombination(
            frei=frei,
            besetzt=besetzt,
            personen=personen,
            vorgaben=vorgaben,
            arten_nach_id=arten_nach_id,
            fachkraftbedarf=fachkraftbedarf,
            ist_fachkraft=ist_fachkraft,
            abwesend=abwesend,
            wuensche=wuensche,
            soll=soll,
            zustand=zustand,
            tempo=tempo,
        )

        if beste is None:
            # Keine Kombination haelt die Vorgabe ein - dann besetzen wie
            # frueher, so weit es geht, und offen lassen, was nicht geht.
            # Eine sichtbare Luecke ist besser als eine stille Fehlplanung.
            beste = _greedy(
                frei=frei,
                personen=personen,
                fachkraftbedarf=fachkraftbedarf,
                ist_fachkraft=ist_fachkraft,
                abwesend=abwesend,
                wuensche=wuensche,
                soll=soll,
                zustand=zustand,
                tempo=tempo,
            )
            bilanz.still_open += len(frei) - len(beste)

        for dienst, person, begruendung in beste:
            dienst.employee = person
            dienst.save(update_fields=["employee"])

            belegt[person.id].append(dienst)
            ist[person.id] += konto_stunden(dienst.shift_type)
            if dienst.date.weekday() >= 5:
                wochenendtage[person.id] += 1
            if ist_fachkraft.get(person.id):
                fachkraefte_gesetzt[(dienst.date, dienst.shift_type_id)] += 1

            bilanz.assigned.append(
                Zuteilung(
                    shift_id=dienst.id,
                    date=str(dienst.date),
                    shift_type=dienst.shift_type.short_code,
                    employee_id=person.id,
                    employee_name=person.get_full_name(),
                    reason=begruendung,
                )
            )

    bilanz.hours = sorted(
        (
            {
                "employee": person.id,
                "name": person.get_full_name(),
                "target": str(soll[person.id]),
                "planned": str(ist[person.id].quantize(Decimal("0.01"))),
                "model": person.work_time_model.name if person.work_time_model else "",
            }
            for person in personen
        ),
        key=lambda eintrag: eintrag["name"],
    )

    if bilanz.still_open:
        bilanz.notes.append(
            f"{bilanz.still_open} Dienste blieben offen. Meist fehlt es an "
            "Ruhezeit, alle infrage kommenden Personen sind an dem Tag schon "
            f"eingeteilt, oder sie stünden sonst mehr als "
            f"{MAX_CONSECUTIVE_DAYS} Tage am Stück im Dienst."
        )

    return bilanz.as_dict()


# Wie viele freie Plaetze ein Tag hoechstens haben darf, bevor der Automat
# aufs Durchprobieren verzichtet.
#
# Er geht alle Teilmengen durch, das sind 2^n. Bei acht Plaetzen sind das
# 256 - nichts. Bei zwanzig waeren es eine Million, je Tag. Darueber besetzt
# er wie frueher der Reihe nach: das Ergebnis ist schlechter verteilt, aber
# es kommt eines.
MAX_PLAETZE_JE_TAG = 10


@dataclass
class _Zustand:
    """Was sich waehrend des Durchlaufs aendert - zum Mitkopieren."""

    belegt: dict
    ist: dict
    wochenendtage: dict
    fachkraefte_gesetzt: dict

    def kopie(self) -> "_Zustand":
        return _Zustand(
            # Als defaultdict, nicht als blankes dict: `_bewerten` und die
            # Zuteilung greifen auf Personen zu, die noch keinen Dienst
            # haben - und die sind hier nicht als Schluessel drin.
            belegt=defaultdict(
                list,
                {person: list(dienste) for person, dienste in self.belegt.items()},
            ),
            ist=defaultdict(lambda: Decimal("0"), self.ist),
            wochenendtage=defaultdict(int, self.wochenendtage),
            fachkraefte_gesetzt=defaultdict(int, self.fachkraefte_gesetzt),
        )


def _stundennutzen(
    person_id, stunden: Decimal, soll: dict, ist: dict, tempo: Decimal
) -> Decimal:
    """
    Was dieser Dienst fuer diese Person wert ist - in Stunden gerechnet.

    Verglichen wird nicht mit dem ganzen Monatssoll, sondern mit dem Teil
    davon, der bis zu diesem Tag faellig waere. Das ist der Punkt: gegen das
    volle Monatssoll gemessen hat am 3. jeder eine riesige Luecke, also
    besetzt der Automat alles, was geht - und ab dem 20. ist niemand mehr
    frei. Am Ende steht ein Monat, in dem alle Ueberstunden haben und die
    letzten Tage offen sind.

    Mit dem Tagestempo bekommt jeder Tag nur den Anteil, der ihm zusteht.
    Wer davor liegt, bringt weniger ein; wer darueber hinausgeht, kostet.
    Damit verteilt sich der Monat von selbst, und was niemand mehr braucht,
    bleibt leer stehen.
    """
    faellig = soll.get(person_id, Decimal("0")) * tempo
    rest = faellig - ist[person_id]
    nutzen = max(Decimal("0"), min(stunden, rest))
    strafe = stunden - nutzen
    return nutzen - strafe


def _deckt_vorgaben(dienste, vorgaben, arten_nach_id) -> bool:
    """Halten diese besetzten Dienste alle Besetzungsvorgaben des Tages ein?"""
    from .bedarf import erfuellt_vorgabe

    anzahlen: dict = defaultdict(int)
    for dienst in dienste:
        anzahlen[dienst.shift_type_id] += 1
    return all(
        erfuellt_vorgabe(vorgabe, anzahlen, arten_nach_id) for vorgabe in vorgaben
    )


def _fachkraefte_reichen(paare, vorgaben, ist_fachkraft) -> bool:
    """
    Steht in jedem Zeitfenster genug Fachpersonal?

    Der Automat achtet auf die Fachkraftquote bisher nur je Dienstart. Eine
    Vorgabe, die sie fuer ein Uhrzeit-Fenster verlangt, greift aber quer
    ueber die Dienstarten - und wenn er eine Kombination waehlt, in der
    nachts nur eine Aushilfe steht, meldet die Regelpruefung hinterher
    genau das.

    Gerechnet wird mit derselben Funktion wie dort, sonst waere die eine
    Antwort die Bedingung und die andere die Beschwerde.

    `paare` sind (Dienst, Personen-Id) - auch die, die schon von Hand
    standen.
    """
    from .rules import faellt_unter

    for vorgabe in vorgaben:
        if not vorgabe.minimum_specialists:
            continue
        fachkraefte = sum(
            1
            for dienst, person_id in paare
            if faellt_unter(vorgabe, dienst)
            and dienst.shift_type.counts_specialist
            and ist_fachkraft.get(person_id)
        )
        if fachkraefte < vorgabe.minimum_specialists:
            return False
    return True


def _versuche(
    frei,
    *,
    personen,
    fachkraftbedarf,
    ist_fachkraft,
    abwesend,
    wuensche,
    soll,
    zustand,
    tempo,
):
    """
    Besetzt genau diese Plaetze - oder gibt auf.

    Arbeitet auf einer Kopie des Zustands: der Aufrufer probiert mehrere
    Kombinationen durch und darf sich dabei nicht die echte Belegung
    zerschreiben.

    Gibt (Zuteilungen, Stundennutzen) zurueck, oder None, wenn auch nur ein
    Platz unbesetzt bliebe. Halb besetzt ist keine Loesung: die
    Besetzungsvorgabe war fuer die ganze Kombination gerechnet.
    """
    arbeits = zustand.kopie()
    ergebnis = []
    nutzen = Decimal("0")

    for dienst in frei:
        schluessel = (dienst.date, dienst.shift_type_id)
        braucht_fachkraft = arbeits.fachkraefte_gesetzt[
            schluessel
        ] < fachkraftbedarf.get(dienst.shift_type_id, 0)

        bester = None
        beste_punkte = None
        beste_begruendung = ""
        for person in personen:
            passt, begruendung, punkte = _bewerten(
                person=person,
                dienst=dienst,
                abwesend=abwesend,
                wuensche=wuensche,
                belegt=arbeits.belegt,
                soll=soll,
                ist=arbeits.ist,
                wochenendtage=arbeits.wochenendtage,
                braucht_fachkraft=braucht_fachkraft,
                ist_fachkraft=ist_fachkraft,
            )
            if not passt:
                continue
            if beste_punkte is None or punkte > beste_punkte:
                bester, beste_punkte, beste_begruendung = person, punkte, begruendung

        if bester is None:
            return None

        stunden = konto_stunden(dienst.shift_type)
        nutzen += _stundennutzen(bester.id, stunden, soll, arbeits.ist, tempo)

        arbeits.belegt[bester.id].append(dienst)
        arbeits.ist[bester.id] += stunden
        if dienst.date.weekday() >= 5:
            arbeits.wochenendtage[bester.id] += 1
        if ist_fachkraft.get(bester.id):
            arbeits.fachkraefte_gesetzt[schluessel] += 1

        ergebnis.append((dienst, bester, beste_begruendung))

    return ergebnis, nutzen


def _beste_kombination(
    *,
    frei,
    besetzt,
    personen,
    vorgaben,
    arten_nach_id,
    fachkraftbedarf,
    ist_fachkraft,
    abwesend,
    wuensche,
    soll,
    zustand,
    tempo,
):
    """
    Welche der freien Plaetze dieser Tag bekommen soll.

    Durchprobiert werden alle Teilmengen, kleine zuerst. Gewaehlt wird die
    mit dem groessten Stundennutzen; bei Gleichstand die kleinere, weil jeder
    Dienst eine Person bindet, die anderswo fehlt.

    Bedingung ist die Besetzungsvorgabe - und zwar zusammen mit dem, was an
    dem Tag schon von Hand steht. Wer den 24-Stunden-Dienst selbst eingeteilt
    hat, soll nicht erleben, dass der Automat daneben noch Tag und Nacht
    besetzt.
    """
    if not vorgaben or len(frei) > MAX_PLAETZE_JE_TAG:
        return None

    beste = None
    beste_bewertung = None

    for groesse in range(len(frei) + 1):
        for auswahl in combinations(frei, groesse):
            if not _deckt_vorgaben(
                list(besetzt) + list(auswahl), vorgaben, arten_nach_id
            ):
                continue

            versuch = _versuche(
                auswahl,
                personen=personen,
                fachkraftbedarf=fachkraftbedarf,
                ist_fachkraft=ist_fachkraft,
                abwesend=abwesend,
                wuensche=wuensche,
                soll=soll,
                zustand=zustand,
                tempo=tempo,
            )
            if versuch is None:
                continue

            zuteilungen, nutzen = versuch

            # Erst jetzt steht fest, WER in der Kombination arbeitet - und
            # damit, ob die Fachkraftquote der Fenster haelt.
            paare = [(d, d.employee_id) for d in besetzt] + [
                (d, person.id) for d, person, _ in zuteilungen
            ]
            if not _fachkraefte_reichen(paare, vorgaben, ist_fachkraft):
                continue

            bewertung = (nutzen, -len(zuteilungen))
            if beste_bewertung is None or bewertung > beste_bewertung:
                beste, beste_bewertung = zuteilungen, bewertung

    return beste


def _greedy(
    *,
    frei,
    personen,
    fachkraftbedarf,
    ist_fachkraft,
    abwesend,
    wuensche,
    soll,
    zustand,
    tempo,
):
    """
    Der Rueckfall: besetzen, so weit es geht, ohne Anspruch auf die beste
    Kombination.

    Greift, wenn der Bereich keine Besetzungsvorgabe hat - dann gibt es
    nichts, wogegen sich eine Kombination pruefen liesse -, wenn ein Tag mehr
    Plaetze hat als sich durchprobieren lassen, oder wenn keine Kombination
    vollstaendig zu besetzen war.
    """
    arbeits = zustand.kopie()
    ergebnis = []

    for dienst in frei:
        versuch = _versuche(
            [dienst],
            personen=personen,
            fachkraftbedarf=fachkraftbedarf,
            ist_fachkraft=ist_fachkraft,
            abwesend=abwesend,
            wuensche=wuensche,
            soll=soll,
            zustand=arbeits,
            tempo=tempo,
        )
        if versuch is None:
            continue

        dienst_, person, begruendung = versuch[0][0]
        ergebnis.append((dienst_, person, begruendung))

        stunden = konto_stunden(dienst.shift_type)
        arbeits.belegt[person.id].append(dienst)
        arbeits.ist[person.id] += stunden
        if dienst.date.weekday() >= 5:
            arbeits.wochenendtage[person.id] += 1
        if ist_fachkraft.get(person.id):
            arbeits.fachkraefte_gesetzt[(dienst.date, dienst.shift_type_id)] += 1

    return ergebnis


def _bewerten(
    *,
    person,
    dienst,
    abwesend,
    wuensche,
    belegt,
    soll,
    ist,
    wochenendtage,
    braucht_fachkraft,
    ist_fachkraft,
) -> tuple[bool, str, float]:
    """
    Passt diese Person auf diesen Dienst, und wie gut?

    Gibt (geht, Begruendung, Punkte) zurueck. Die Begruendung landet im
    Bericht - wer den Automaten in Frage stellt, soll nachlesen koennen,
    warum er wen genommen hat.
    """
    # --- Harte Ausschluesse

    if dienst.date in abwesend.get(person.id, ()):
        return False, "", 0

    wunsch_art = wuensche.get(
        (person.id, dienst.date, dienst.shift_type_id)
    ) or wuensche.get((person.id, dienst.date, None))
    if wunsch_art == "unavailable":
        return False, "", 0

    for anderer in belegt.get(person.id, ()):
        if anderer.date == dienst.date:
            return False, "", 0
        # Ueberschneidung und Ruhezeit in einem: ruhezeit() gibt None
        # zurueck, wenn zwei Dienste zur selben Zeit laufen - und das koennen
        # sie auch an verschiedenen Kalendertagen, sobald einer ueber
        # Mitternacht geht.
        pause = ruhezeit(anderer, dienst)
        if pause is None:
            return False, "", 0
        if timedelta(0) <= pause < timedelta(hours=MIN_REST_HOURS):
            return False, "", 0

    # Nach spaetestens sechs Tagen ein freier Tag (§ 11 Abs. 3 ArbZG).
    #
    # Der Automat kannte diese Regel gar nicht - er pruefte Ruhezeit und
    # Doppelbelegung, und teilte eine Person ohne Weiteres sieben Tage am
    # Stueck ein. Die Regelpruefung meldete das hinterher; hinterher ist
    # aber der falsche Zeitpunkt, wenn ein Automat den Plan gebaut hat.
    #
    # serie_um zaehlt in beide Richtungen: ein einzelner Tag zwischen zwei
    # Serien verbindet sie, und der faellt sonst durch.
    tage = {anderer.date for anderer in belegt.get(person.id, ())}
    if serie_um(tage, dienst.date) > MAX_CONSECUTIVE_DAYS:
        return False, "", 0

    # --- Punkte

    gruende = []
    punkte = 0.0

    monatssoll = soll.get(person.id) or Decimal("0")
    geplant = ist.get(person.id) or Decimal("0")
    if monatssoll > 0:
        luecke = float((monatssoll - geplant) / monatssoll)
        punkte += luecke * GEWICHT_STUNDENLUECKE
        if geplant >= monatssoll * UEBERSTUNDEN_TOLERANZ:
            punkte -= ABZUG_UEBER_SOLL
            gruende.append("bereits über dem Monatssoll")
        elif luecke > 0.25:
            gruende.append(
                f"noch {(monatssoll - geplant).quantize(Decimal('0.1'))} h offen"
            )
    else:
        # Ohne Arbeitszeitmodell gibt es kein Soll. Solche Personen kommen
        # zuletzt dran, statt gar nicht - sonst faellt eine Aushilfe ohne
        # hinterlegtes Modell stillschweigend aus der Planung.
        punkte -= 10

    if wunsch_art == "wish":
        punkte += GEWICHT_WUNSCH
        gruende.append("hat sich den Tag gewünscht")
    elif wunsch_art == "block":
        punkte -= ABZUG_MOECHTE_NICHT
        gruende.append("wollte den Tag eigentlich nicht")

    if braucht_fachkraft:
        if ist_fachkraft.get(person.id):
            punkte += GEWICHT_FACHKRAFT
            gruende.append("Fachkraft, hier vorgeschrieben")
        else:
            punkte -= GEWICHT_FACHKRAFT

    if dienst.date.weekday() >= 5:
        bisher = wochenendtage.get(person.id, 0)
        punkte -= bisher * ABZUG_JE_WOCHENENDTAG
        if bisher >= 4:
            gruende.append(f"schon {bisher} Wochenendtage")

    if dienst.shift_type.counts_specialist and ist_fachkraft.get(person.id):
        punkte += VORZUG_QUOTENDIENST

    return True, " · ".join(gruende) or "passt ohne Einschränkung", punkte
