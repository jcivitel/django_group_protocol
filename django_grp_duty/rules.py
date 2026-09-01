"""
Regelprüfung für Dienstpläne.

Die Prüfungen laufen auf Anfrage über einen ganzen Plan und geben Verstöße
zurück, statt sie zu speichern. So bleibt der Plan bearbeitbar und die
Meldungen sind immer aktuell.

Die Grenzwerte folgen dem Arbeitszeitgesetz (§ 3 und § 5 ArbZG) und den
Vorgaben, die je Bereich hinterlegt sind (Mindestbesetzung, Fachkraftquote).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

# § 5 ArbZG: mindestens 11 Stunden ununterbrochene Ruhezeit.
MIN_REST_HOURS = 11

# § 3 ArbZG: werktäglich höchstens 10 Stunden.
MAX_SHIFT_HOURS = Decimal("10")

# Höchstens so viele Tage am Stück im Dienst.
MAX_CONSECUTIVE_DAYS = 7


@dataclass
class Violation:
    """Ein einzelner Regelverstoß, verständlich formuliert."""

    rule: str
    severity: str  # "error" oder "warning"
    date: str
    message: str
    shift_id: int | None = None
    employee_id: int | None = None

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "date": self.date,
            "message": self.message,
            "shift": self.shift_id,
            "employee": self.employee_id,
        }


def check_plan(plan) -> list[Violation]:
    """Prüft einen Dienstplan vollständig und gibt alle Verstöße zurück."""
    shifts = list(
        plan.shifts.select_related("shift_type", "employee").order_by(
            "date", "shift_type__start_time"
        )
    )

    violations: list[Violation] = []
    violations += _check_open_shifts(shifts)
    violations += _check_shift_length(shifts)
    violations += _check_rest_periods(shifts)
    violations += _check_double_booking(shifts)
    violations += _check_absences(shifts)
    violations += _check_consecutive_days(shifts)
    violations += _check_staffing(plan, shifts)
    return violations


def _check_open_shifts(shifts) -> list[Violation]:
    return [
        Violation(
            rule="open_shift",
            severity="error",
            date=str(shift.date),
            message=f"{shift.shift_type.name} ist nicht besetzt.",
            shift_id=shift.id,
        )
        for shift in shifts
        if shift.employee_id is None
    ]


def _check_shift_length(shifts) -> list[Violation]:
    out = []
    for shift in shifts:
        hours = shift.shift_type.duration_hours
        if hours > MAX_SHIFT_HOURS and not shift.shift_type.is_on_call:
            out.append(
                Violation(
                    rule="shift_length",
                    severity="warning",
                    date=str(shift.date),
                    message=(
                        f"{shift.shift_type.name} dauert {hours} Stunden – "
                        f"über der werktäglichen Höchstarbeitszeit von "
                        f"{MAX_SHIFT_HOURS} Stunden."
                    ),
                    shift_id=shift.id,
                    employee_id=shift.employee_id,
                )
            )
    return out


def _by_employee(shifts):
    grouped = defaultdict(list)
    for shift in shifts:
        if shift.employee_id:
            grouped[shift.employee_id].append(shift)
    return grouped


def _check_rest_periods(shifts) -> list[Violation]:
    out = []
    for employee_id, entries in _by_employee(shifts).items():
        ordered = sorted(entries, key=lambda item: item.starts_at)
        for previous, current in zip(ordered, ordered[1:]):
            rest = current.starts_at - previous.ends_at
            if rest < timedelta(hours=MIN_REST_HOURS):
                hours = round(rest.total_seconds() / 3600, 1)
                out.append(
                    Violation(
                        rule="rest_period",
                        severity="error",
                        date=str(current.date),
                        message=(
                            f"{current.employee.get_full_name()} hat nur {hours} "
                            f"Stunden Ruhezeit zwischen {previous.shift_type.short_code} "
                            f"am {previous.date:%d.%m.} und {current.shift_type.short_code} – "
                            f"vorgeschrieben sind {MIN_REST_HOURS}."
                        ),
                        shift_id=current.id,
                        employee_id=employee_id,
                    )
                )
    return out


def _check_double_booking(shifts) -> list[Violation]:
    out = []
    for employee_id, entries in _by_employee(shifts).items():
        ordered = sorted(entries, key=lambda item: item.starts_at)
        for previous, current in zip(ordered, ordered[1:]):
            if current.starts_at < previous.ends_at:
                out.append(
                    Violation(
                        rule="double_booking",
                        severity="error",
                        date=str(current.date),
                        message=(
                            f"{current.employee.get_full_name()} ist gleichzeitig für "
                            f"{previous.shift_type.short_code} und "
                            f"{current.shift_type.short_code} eingeteilt."
                        ),
                        shift_id=current.id,
                        employee_id=employee_id,
                    )
                )
    return out


def _check_absences(shifts) -> list[Violation]:
    from .models import Absence

    employee_ids = {shift.employee_id for shift in shifts if shift.employee_id}
    if not employee_ids:
        return []

    dates = [shift.date for shift in shifts]
    absences = Absence.objects.filter(
        employee_id__in=employee_ids,
        status="approved",
        start_date__lte=max(dates),
        end_date__gte=min(dates),
    ).select_related("absence_type", "employee")

    out = []
    for shift in shifts:
        if not shift.employee_id:
            continue
        for absence in absences:
            if absence.employee_id == shift.employee_id and absence.covers(shift.date):
                out.append(
                    Violation(
                        rule="absence_conflict",
                        severity="error",
                        date=str(shift.date),
                        message=(
                            f"{shift.employee.get_full_name()} ist an diesem Tag "
                            f"abwesend ({absence.absence_type.name}), steht aber im "
                            f"Dienst {shift.shift_type.short_code}."
                        ),
                        shift_id=shift.id,
                        employee_id=shift.employee_id,
                    )
                )
                break
    return out


def _check_consecutive_days(shifts) -> list[Violation]:
    out = []
    for employee_id, entries in _by_employee(shifts).items():
        days = sorted({shift.date for shift in entries})
        if not days:
            continue

        streak_start = days[0]
        streak = 1
        for previous, current in zip(days, days[1:]):
            if (current - previous).days == 1:
                streak += 1
            else:
                streak_start = current
                streak = 1

            if streak > MAX_CONSECUTIVE_DAYS:
                name = entries[0].employee.get_full_name()
                out.append(
                    Violation(
                        rule="consecutive_days",
                        severity="warning",
                        date=str(current),
                        message=(
                            f"{name} arbeitet seit {streak_start:%d.%m.} durchgehend "
                            f"{streak} Tage."
                        ),
                        employee_id=employee_id,
                    )
                )
                break
    return out


def _check_staffing(plan, shifts) -> list[Violation]:
    """Mindestbesetzung und Fachkraftquote je Tag prüfen."""
    department = plan.department
    per_day = defaultdict(list)
    for shift in shifts:
        per_day[shift.date].append(shift)

    out = []
    for day, entries in sorted(per_day.items()):
        staffed = [shift for shift in entries if shift.employee_id]

        if len(staffed) < department.minimum_staff:
            out.append(
                Violation(
                    rule="minimum_staff",
                    severity="error",
                    date=str(day),
                    message=(
                        f"Nur {len(staffed)} von mindestens "
                        f"{department.minimum_staff} Personen im Dienst."
                    ),
                )
            )

        counting = [shift for shift in staffed if shift.shift_type.counts_specialist]
        if counting and department.specialist_ratio:
            specialists = [shift for shift in counting if shift.employee.is_specialist]
            share = round(len(specialists) * 100 / len(counting))
            if share < department.specialist_ratio:
                out.append(
                    Violation(
                        rule="specialist_ratio",
                        severity="warning",
                        date=str(day),
                        message=(
                            f"Fachkraftanteil {share} % – gefordert sind "
                            f"{department.specialist_ratio} %."
                        ),
                    )
                )
    return out
