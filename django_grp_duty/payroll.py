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
from django.db import models

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
    "saturday": ("1550", "Samstagsstunden"),
    "vacation": ("3000", "Urlaubstage"),
    "sick": ("3100", "Krankheitstage"),
    # Betraege statt Stunden. Sie entstehen nur, wenn am Traeger ein
    # Zuschlagssatz und an der Entgeltgruppe ein Betrag steht.
    "night_amount": ("2300", "Nachtzuschlag"),
    "holiday_amount": ("2400", "Feiertagszuschlag"),
    "sunday_amount": ("2500", "Sonntagszuschlag"),
    "saturday_amount": ("2550", "Samstagszuschlag"),
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


def _zuschlagsstunden(employee, year: int, month: int) -> dict[str, Decimal]:
    """
    Stunden an Feiertagen, Sonntagen und Samstagen.

    Zaehlt die geplanten Dienste, nicht die Zeitbuchungen: die Zuschlagsfrage
    haengt am Kalendertag, und der steht am Dienst. Ein Dienst ueber
    Mitternacht wird dem Tag zugeordnet, an dem er beginnt - das ist die
    uebliche Handhabung und die einzige, die ohne Aufteilung auskommt.

    Die Prozentsaetze stehen weiterhin nicht hier, sondern als
    `SurchargeRate` am Traeger - siehe `django_grp_org/entgelt.py`. Ist dort
    keiner gepflegt, uebergibt die Abrechnung nur die Stunden, wie zuvor.
    """
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    feiertage = feiertage_im_zeitraum(employee.provider, first, last)

    stunden_je_art = {
        "holiday": Decimal("0"),
        "sunday": Decimal("0"),
        "saturday": Decimal("0"),
    }

    dienste = Shift.objects.filter(
        employee=employee, date__gte=first, date__lte=last
    ).select_related("shift_type")

    for dienst in dienste:
        stunden = dienst.shift_type.duration_hours
        # Genau ein Topf je Dienst. Faellt mehreres zusammen, zaehlt der
        # hoeherwertige - sonst stuende dieselbe Stunde zweimal in der
        # Abrechnung.
        if dienst.date in feiertage:
            stunden_je_art["holiday"] += stunden
        elif dienst.date.weekday() == 6:
            stunden_je_art["sunday"] += stunden
        elif dienst.date.weekday() == 5:
            stunden_je_art["saturday"] += stunden

    return {
        art: wert.quantize(Decimal("0.01")) for art, wert in stunden_je_art.items()
    }


def _stundenentgelt(employee, stichtag) -> Decimal | None:
    """
    Was eine Stunde dieser Person kostet.

    Monatsentgelt der Entgeltgruppe und Stufe, geteilt durch die
    Monatsstunden. Fehlt eines der drei Stuecke - Vertrag mit Gruppe und
    Stufe, Betrag an der Stufe, Wochenstunden -, kommt None zurueck und die
    Abrechnung bleibt bei den Stunden.

    Lieber keine Zahl als eine, die auf einer Annahme steht.
    """
    vertrag = (
        employee.contracts.filter(valid_from__lte=stichtag)
        .filter(models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=stichtag))
        .select_related("pay_grade_ref")
        .order_by("-valid_from")
        .first()
    )
    if vertrag is None or vertrag.pay_grade_ref is None or not vertrag.pay_step:
        return None

    monatsentgelt = vertrag.pay_grade_ref.betrag_am(vertrag.pay_step, stichtag)
    if not monatsentgelt:
        return None

    wochenstunden = vertrag.weekly_hours or (
        employee.work_time_model.weekly_hours if employee.work_time_model else None
    )
    if not wochenstunden:
        return None

    monatsstunden = Decimal(wochenstunden) * employee.provider.monthly_hours_factor
    if monatsstunden <= 0:
        return None
    return (Decimal(monatsentgelt) / monatsstunden).quantize(Decimal("0.0001"))


def _zuschlagssaetze(provider) -> dict:
    """Die gepflegten Saetze des Traegers, Art zu Prozent."""
    from django_grp_org.models import SurchargeRate

    return {
        satz.kind: satz.percent
        for satz in SurchargeRate.objects.filter(provider=provider)
        if satz.percent
    }


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
    saetze_je_traeger: dict = {}

    for account in accounts:
        employee = account.employee
        if employee.provider_id not in saetze_je_traeger:
            saetze_je_traeger[employee.provider_id] = _zuschlagssaetze(
                employee.provider
            )
        saetze = saetze_je_traeger[employee.provider_id]
        balance = account.balance

        entries = [
            ("base", min(account.actual_hours, account.target_hours)),
            ("overtime", balance if balance > 0 else Decimal("0")),
            ("shortfall", -balance if balance < 0 else Decimal("0")),
            ("on_call", account.on_call_hours),
            ("night", account.night_hours),
        ]

        zuschlagsstunden = _zuschlagsstunden(employee, year, month)
        entries += [
            ("holiday", zuschlagsstunden["holiday"]),
            ("sunday", zuschlagsstunden["sunday"]),
            ("saturday", zuschlagsstunden["saturday"]),
        ]

        day_entries = [
            ("vacation", Decimal(_absence_days(employee, year, month, "vacation"))),
            ("sick", Decimal(_absence_days(employee, year, month, "sick"))),
        ]

        # Zuschlagsbetraege, sofern Satz und Stundenentgelt gepflegt sind.
        # Nachtstunden kommen aus dem Zeitkonto, die uebrigen aus dem Plan.
        stundensatz = _stundenentgelt(employee, date(year, month, 1))
        betraege = []
        if stundensatz:
            grundlage = {
                "night": account.night_hours,
                "holiday": zuschlagsstunden["holiday"],
                "sunday": zuschlagsstunden["sunday"],
                "saturday": zuschlagsstunden["saturday"],
            }
            for art, satz in saetze.items():
                stunden = grundlage.get(art) or Decimal("0")
                if not stunden:
                    continue
                betrag = (
                    Decimal(stunden) * stundensatz * satz / Decimal("100")
                ).quantize(Decimal("0.01"))
                if betrag:
                    betraege.append((art + "_amount", betrag))

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

        for key, amount in betraege:
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
                    "amount": str(amount),
                    "unit": "Euro",
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
