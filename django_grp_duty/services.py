"""
Fachlogik zur Dienstplanung: Vertretungssuche und Monatsabschluss.

Getrennt von den ViewSets, damit dieselbe Logik auch aus dem Admin, aus
Skripten oder später aus einem Cron-Job genutzt werden kann.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q

from django_grp_org.models import Employee

from .models import Absence, Shift, TimeAccount, TimeEntry
from .rules import MIN_REST_HOURS


def find_substitutes(shift) -> list[dict]:
    """
    Sucht Personen, die einen offenen Dienst übernehmen könnten.

    Sortiert nach Eignung: erst wer alle Bedingungen erfüllt, dann wer nur
    weiche Kriterien verletzt. Ausgeschlossen wird niemand stillschweigend -
    jede Einschränkung steht als Grund dabei, damit die Planung entscheiden
    kann.
    """
    department = shift.plan.department
    provider = department.facility.site.provider

    candidates = (
        Employee.objects.filter(provider=provider, left_on__isnull=True)
        .exclude(id=shift.employee_id)
        .prefetch_related("qualifications")
    )

    # Abwesenheiten und andere Dienste am selben Tag einmal vorladen.
    absent_ids = set(
        Absence.objects.filter(
            status="approved",
            start_date__lte=shift.date,
            end_date__gte=shift.date,
        ).values_list("employee_id", flat=True)
    )

    same_day = (
        Shift.objects.filter(
            date__in=[
                shift.date - timedelta(days=1),
                shift.date,
                shift.date + timedelta(days=1),
            ],
            employee__isnull=False,
        )
        .exclude(id=shift.id)
        .select_related("shift_type")
    )

    shifts_by_employee: dict[int, list] = {}
    for entry in same_day:
        shifts_by_employee.setdefault(entry.employee_id, []).append(entry)

    results = []
    for employee in candidates:
        reasons = []
        blocked = False

        if employee.id in absent_ids:
            reasons.append("ist an diesem Tag abwesend")
            blocked = True

        for other in shifts_by_employee.get(employee.id, []):
            if other.date == shift.date:
                reasons.append(f"hat am selben Tag {other.shift_type.short_code}")
                blocked = True
                continue
            # Ruhezeit zum Vor- oder Folgetag prüfen.
            gap = (
                shift.starts_at - other.ends_at
                if other.ends_at <= shift.starts_at
                else other.starts_at - shift.ends_at
            )
            if timedelta(0) <= gap < timedelta(hours=MIN_REST_HOURS):
                hours = round(gap.total_seconds() / 3600, 1)
                reasons.append(
                    f"nur {hours} h Ruhezeit zu {other.shift_type.short_code}"
                )
                blocked = True

        is_specialist = employee.is_specialist
        if shift.shift_type.counts_specialist and not is_specialist:
            reasons.append("keine Fachkraftqualifikation")

        in_department = employee.assignments.filter(
            position__department=department
        ).exists()
        if not in_department:
            reasons.append("arbeitet sonst nicht in diesem Bereich")

        results.append(
            {
                "employee": employee.id,
                "name": employee.get_full_name(),
                "is_specialist": is_specialist,
                "in_department": in_department,
                "available": not blocked,
                "reasons": reasons,
            }
        )

    # Verfügbar zuerst, dann bereichseigene, dann Fachkräfte.
    results.sort(
        key=lambda entry: (
            not entry["available"],
            not entry["in_department"],
            not entry["is_specialist"],
            entry["name"],
        )
    )
    return results


def release_shifts_for_absence(absence) -> int:
    """
    Gibt Dienste frei, die durch eine genehmigte Abwesenheit ausfallen.

    Der Dienst bleibt bestehen und wird nur unbesetzt - so sieht die Planung
    die Lücke, statt dass der Bedarf verschwindet.
    """
    if absence.status != "approved":
        return 0

    affected = Shift.objects.filter(
        employee_id=absence.employee_id,
        date__gte=absence.start_date,
        date__lte=absence.end_date,
    )
    count = affected.count()
    for shift in affected:
        note = f"Frei geworden: {absence.absence_type.name}"
        shift.employee = None
        shift.note = note if not shift.note else f"{shift.note} · {note}"
        shift.save(update_fields=["employee", "note"])
    return count


def target_hours_for_month(employee, year: int, month: int) -> Decimal:
    """
    Soll-Stunden eines Monats aus dem Arbeitszeitmodell.

    Gerechnet wird über die Werktage im Monat, weil das Arbeitszeitmodell
    Wochenstunden und Tage pro Woche vorgibt. Feiertage kennt das System
    noch nicht - sie müssten als Abwesenheit erfasst werden.
    """
    model = employee.work_time_model
    if not model:
        return Decimal("0")

    days_in_month = calendar.monthrange(year, month)[1]
    weekdays = sum(
        1 for day in range(1, days_in_month + 1) if date(year, month, day).weekday() < 5
    )
    daily = model.weekly_hours / (model.days_per_week or Decimal("5"))
    return (daily * weekdays).quantize(Decimal("0.01"))


def close_month(employee, year: int, month: int) -> TimeAccount:
    """
    Schließt ein Zeitkonto ab: Ist-Stunden summieren, Übertrag fortschreiben.

    Erneutes Aufrufen rechnet neu - so lassen sich nachgetragene Buchungen
    berücksichtigen, solange der Monat nicht endgültig festgeschrieben ist.
    """
    days_in_month = calendar.monthrange(year, month)[1]
    entries = TimeEntry.objects.filter(
        employee=employee,
        date__gte=date(year, month, 1),
        date__lte=date(year, month, days_in_month),
    ).select_related("shift__shift_type")

    actual = Decimal("0")
    on_call = Decimal("0")
    night = Decimal("0")
    for entry in entries:
        actual += entry.credited_hours
        if entry.category == "on_call":
            on_call += entry.hours
        if entry.shift and entry.shift.shift_type.is_night:
            night += entry.hours

    previous_year, previous_month = (year, month - 1) if month > 1 else (year - 1, 12)
    previous = TimeAccount.objects.filter(
        employee=employee, year=previous_year, month=previous_month
    ).first()
    carry_over = previous.balance if previous else Decimal("0")

    account, _ = TimeAccount.objects.update_or_create(
        employee=employee,
        year=year,
        month=month,
        defaults={
            "target_hours": target_hours_for_month(employee, year, month),
            "actual_hours": actual.quantize(Decimal("0.01")),
            "on_call_hours": on_call.quantize(Decimal("0.01")),
            "night_hours": night.quantize(Decimal("0.01")),
            "carry_over": carry_over,
        },
    )
    return account


def vacation_balance(employee, year: int) -> dict:
    """Urlaubsanspruch, genommene und verbleibende Tage eines Jahres."""
    model = employee.work_time_model
    entitlement = model.vacation_days if model else 0

    taken = 0
    requested = 0
    absences = Absence.objects.filter(
        employee=employee,
        absence_type__reduces_vacation=True,
        start_date__year=year,
    ).select_related("absence_type")

    for absence in absences:
        if absence.status == "approved":
            taken += absence.days
        elif absence.status == "requested":
            requested += absence.days

    return {
        "entitlement": entitlement,
        "taken": taken,
        "requested": requested,
        "remaining": entitlement - taken - requested,
    }


def generate_shifts(plan, shift_types, weekdays=None) -> int:
    """
    Legt für einen Monat die Dienste an, zunächst alle unbesetzt.

    `weekdays` schränkt auf bestimmte Wochentage ein (0 = Montag). Bereits
    vorhandene Dienste bleiben unberührt, damit ein zweiter Aufruf nichts
    doppelt anlegt.
    """
    days_in_month = calendar.monthrange(plan.year, plan.month)[1]
    existing = set(plan.shifts.values_list("date", "shift_type_id"))

    created = 0
    for day in range(1, days_in_month + 1):
        current = date(plan.year, plan.month, day)
        if weekdays is not None and current.weekday() not in weekdays:
            continue
        for shift_type in shift_types:
            if (current, shift_type.id) in existing:
                continue
            Shift.objects.create(plan=plan, date=current, shift_type=shift_type)
            created += 1
    return created
