"""
Übergabe an die Lohnabrechnung (Roadmap Phase 4).

Erzeugt je Person und Monat Zeilen nach Lohnarten - das Format, das
Lohnprogramme wie DATEV Lohn und Gehalt erwarten: eine Zeile je
Personalnummer und Lohnart mit der abzurechnenden Menge.

Die Nummern der Lohnarten sind je Träger verschieden. Deshalb stehen sie
hier als Vorgabe und lassen sich über PAYROLL_WAGE_TYPES in den Settings
überschreiben, ohne den Code anzufassen.
"""

import calendar
from datetime import date
from decimal import Decimal

from django.conf import settings

from django_grp_org.models import Employee
from django_grp_org.tenancy import limit_to_tenant

from .models import Absence, TimeAccount

# Vorgabe: Lohnart-Nummer und Bezeichnung je Größe.
DEFAULT_WAGE_TYPES = {
    "base": ("1000", "Grundstunden"),
    "overtime": ("1100", "Mehrarbeit"),
    "shortfall": ("1150", "Minderstunden"),
    "on_call": ("1200", "Bereitschaft"),
    "night": ("1300", "Nachtstunden"),
    "vacation": ("3000", "Urlaubstage"),
    "sick": ("3100", "Krankheitstage"),
}


def wage_types() -> dict:
    override = getattr(settings, "PAYROLL_WAGE_TYPES", None) or {}
    merged = dict(DEFAULT_WAGE_TYPES)
    for key, value in override.items():
        merged[key] = tuple(value)
    return merged


def _absence_days(employee, year: int, month: int, kind: str) -> int:
    """Tage einer Abwesenheitsart, die in diesen Monat fallen."""
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])

    total = 0
    absences = Absence.objects.filter(
        employee=employee,
        status="approved",
        absence_type__kind=kind,
        start_date__lte=last,
        end_date__gte=first,
    )
    for absence in absences:
        start = max(absence.start_date, first)
        end = min(absence.end_date, last)
        total += (end - start).days + 1
    return total


def build_rows(user, year: int, month: int) -> list[dict]:
    """
    Abrechnungszeilen für einen Monat.

    Grundlage sind die abgeschlossenen Zeitkonten: erst der Monatsabschluss
    macht die Stunden abrechenbar. Ohne Zeitkonto entsteht keine Zeile -
    das ist Absicht, damit nichts Vorläufiges in die Lohnabrechnung gerät.
    """
    types = wage_types()
    accounts = limit_to_tenant(
        TimeAccount.objects.filter(year=year, month=month).select_related("employee"),
        user,
        "employee__provider_id",
    )

    rows: list[dict] = []
    for account in accounts:
        employee = account.employee
        balance = account.balance

        entries = [
            ("base", min(account.actual_hours, account.target_hours)),
            ("overtime", balance if balance > 0 else Decimal("0")),
            ("shortfall", -balance if balance < 0 else Decimal("0")),
            ("on_call", account.on_call_hours),
            ("night", account.night_hours),
        ]

        day_entries = [
            ("vacation", Decimal(_absence_days(employee, year, month, "vacation"))),
            ("sick", Decimal(_absence_days(employee, year, month, "sick"))),
        ]

        for key, amount in entries + day_entries:
            if not amount:
                continue
            number, label = types[key]
            rows.append(
                {
                    "personnel_number": employee.personnel_number
                    or f"MA{employee.id:05d}",
                    "name": employee.get_full_name(),
                    "year": year,
                    "month": month,
                    "wage_type": number,
                    "wage_label": label,
                    "amount": str(Decimal(amount).quantize(Decimal("0.01"))),
                    "unit": "Tage" if key in ("vacation", "sick") else "Stunden",
                }
            )

    rows.sort(key=lambda row: (row["personnel_number"], row["wage_type"]))
    return rows


def missing_accounts(user, year: int, month: int) -> list[str]:
    """
    Wer hat für diesen Monat kein abgeschlossenes Zeitkonto?

    Wird der Ausgabe beigelegt, damit niemand eine unvollständige Datei für
    vollständig hält.
    """
    closed = set(
        TimeAccount.objects.filter(year=year, month=month).values_list(
            "employee_id", flat=True
        )
    )
    employees = limit_to_tenant(Employee.objects.filter(left_on__isnull=True), user)
    return [
        employee.get_full_name() for employee in employees if employee.id not in closed
    ]
