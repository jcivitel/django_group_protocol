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

from django_grp_org.holiday_service import feiertage_im_zeitraum

from .models import Absence, Shift, TimeAccount

# Vorgabe: Lohnart-Nummer und Bezeichnung je Größe.
DEFAULT_WAGE_TYPES = {
    "base": ("1000", "Grundstunden"),
    "overtime": ("1100", "Mehrarbeit"),
    "shortfall": ("1150", "Minderstunden"),
    "on_call": ("1200", "Bereitschaft"),
    "night": ("1300", "Nachtstunden"),
    "holiday": ("1400", "Feiertagsstunden"),
    "sunday": ("1500", "Sonntagsstunden"),
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


def _zuschlagsstunden(employee, year: int, month: int) -> tuple[Decimal, Decimal]:
    """
    Stunden an Feiertagen und an Sonntagen.

    Zaehlt die geplanten Dienste, nicht die Zeitbuchungen: die Zuschlagsfrage
    haengt am Kalendertag, und der steht am Dienst. Ein Dienst ueber
    Mitternacht wird dem Tag zugeordnet, an dem er beginnt - das ist die
    uebliche Handhabung und die einzige, die ohne Aufteilung auskommt.

    Die Prozentsaetze stehen hier bewusst nicht: sie folgen dem Tarifwerk
    (TVoeD SuE kennt andere als AVR oder Haustarif), und eine falsche Zahl im
    Code waere schlimmer als gar keine. Uebergeben werden die Stunden, den
    Satz rechnet die Lohnabrechnung.
    """
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    feiertage = feiertage_im_zeitraum(employee.provider, first, last)

    feiertagsstunden = Decimal("0")
    sonntagsstunden = Decimal("0")

    dienste = Shift.objects.filter(
        employee=employee, date__gte=first, date__lte=last
    ).select_related("shift_type")

    for dienst in dienste:
        stunden = dienst.shift_type.duration_hours
        if dienst.date in feiertage:
            feiertagsstunden += stunden
        elif dienst.date.weekday() == 6:
            # Faellt beides zusammen, zaehlt der Feiertag - sonst stuende
            # dieselbe Stunde zweimal in der Abrechnung.
            sonntagsstunden += stunden

    return (
        feiertagsstunden.quantize(Decimal("0.01")),
        sonntagsstunden.quantize(Decimal("0.01")),
    )


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

        feiertagsstunden, sonntagsstunden = _zuschlagsstunden(employee, year, month)
        entries += [
            ("holiday", feiertagsstunden),
            ("sunday", sonntagsstunden),
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
