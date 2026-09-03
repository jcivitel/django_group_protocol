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
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django_grp_org.models import Employee

from .models import Absence, Shift, ShiftPreference, StaffingRequirement
from .rules import MIN_REST_HOURS
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


def _mitarbeitende(department) -> list[Employee]:
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


def _stunden(shift_type) -> Decimal:
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

    personen = _mitarbeitende(department)
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
    belegt: dict[int, list] = defaultdict(list)
    for fremd in (
        Shift.objects.filter(
            date__gte=von - timedelta(days=1),
            date__lte=bis + timedelta(days=1),
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
            ist[dienst.employee_id] += _stunden(dienst.shift_type)

    wochenendtage: dict[int, int] = defaultdict(int)
    for dienst in dienste:
        if dienst.employee_id and dienst.date.weekday() >= 5:
            wochenendtage[dienst.employee_id] += 1

    # --- Der eigentliche Durchlauf.

    fachkraefte_gesetzt: dict[tuple, int] = defaultdict(int)
    for dienst in dienste:
        if dienst.employee_id and ist_fachkraft.get(dienst.employee_id):
            fachkraefte_gesetzt[(dienst.date, dienst.shift_type_id)] += 1

    for dienst in offen:
        schluessel = (dienst.date, dienst.shift_type_id)
        braucht_fachkraft = fachkraefte_gesetzt[schluessel] < fachkraftbedarf.get(
            dienst.shift_type_id, 0
        )

        bester = None
        beste_punkte = None
        beste_begruendung = ""

        for person in personen:
            passt, begruendung, punkte = _bewerten(
                person=person,
                dienst=dienst,
                abwesend=abwesend,
                wuensche=wuensche,
                belegt=belegt,
                soll=soll,
                ist=ist,
                wochenendtage=wochenendtage,
                braucht_fachkraft=braucht_fachkraft,
                ist_fachkraft=ist_fachkraft,
            )
            if not passt:
                continue
            if beste_punkte is None or punkte > beste_punkte:
                bester, beste_punkte, beste_begruendung = person, punkte, begruendung

        if bester is None:
            bilanz.still_open += 1
            continue

        dienst.employee = bester
        dienst.save(update_fields=["employee"])

        belegt[bester.id].append(dienst)
        ist[bester.id] += _stunden(dienst.shift_type)
        if dienst.date.weekday() >= 5:
            wochenendtage[bester.id] += 1
        if ist_fachkraft.get(bester.id):
            fachkraefte_gesetzt[schluessel] += 1

        bilanz.assigned.append(
            Zuteilung(
                shift_id=dienst.id,
                date=str(dienst.date),
                shift_type=dienst.shift_type.short_code,
                employee_id=bester.id,
                employee_name=bester.get_full_name(),
                reason=beste_begruendung,
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
            "Ruhezeit oder alle infrage kommenden Personen sind an dem Tag "
            "schon eingeteilt."
        )

    return bilanz.as_dict()


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
