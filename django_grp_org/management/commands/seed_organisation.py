"""
Legt die Organisationsstruktur aus dem vorhandenen Bestand an.

Aus den bestehenden Gruppen und Benutzerkonten entsteht ein Träger mit
Standort, Einrichtung, Bereichen, Mitarbeitenden, Dienstarten und
Abwesenheitsarten - genug, damit Dienstplanung, Abwesenheiten und
Zeiterfassung sofort benutzbar sind.

Der Befehl ist wiederholbar: vorhandene Datensätze werden erkannt und nicht
doppelt angelegt. Bestehende Daten werden nie überschrieben.

    python manage.py seed_organisation
    python manage.py seed_organisation --provider "Caritasverband Musterstadt"
"""

from datetime import date, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from django_grp_backend.models import Group
from django_grp_duty.models import AbsenceType, ShiftType
from django_grp_org.models import (
    Department,
    Employee,
    Facility,
    Position,
    Provider,
    Qualification,
    Role,
    Site,
    WorkTimeModel,
)

QUALIFICATIONS = [
    ("Erzieher:in", True),
    ("Sozialpädagog:in (B.A.)", True),
    ("Heilerziehungspfleger:in", True),
    ("Kinderpfleger:in", False),
    ("Erste Hilfe (Auffrischung)", False),
    ("Deeskalationstraining", False),
]

SHIFT_TYPES = [
    ("Frühdienst", "F", time(6, 30), time(14, 30), 30, "#abc270", False, False),
    ("Spätdienst", "S", time(13, 30), time(21, 30), 30, "#fec868", False, False),
    ("Nachtbereitschaft", "N", time(21, 0), time(7, 0), 0, "#473c33", True, True),
    ("Zwischendienst", "Z", time(10, 0), time(18, 0), 30, "#fda769", False, False),
    ("Wochenende lang", "WE", time(8, 0), time(20, 0), 60, "#7e9a4e", False, False),
]

ABSENCE_TYPES = [
    ("Urlaub", "vacation", True, True, "#abc270"),
    ("Krankheit", "sick", False, False, "#a63d18"),
    ("Fortbildung", "training", False, True, "#fda769"),
    ("Sonderurlaub", "special", False, True, "#fec868"),
    ("Unbezahlt", "unpaid", False, True, "#8a7c6f"),
]


class Command(BaseCommand):
    help = "Legt Träger, Organisationsstruktur und Stammdaten aus dem Bestand an."

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider",
            default="Träger",
            help="Name des Trägers, falls noch keiner existiert",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        provider = self._provider(options["provider"])
        site = self._site(provider)
        work_time_models = self._work_time_models(provider)
        self._qualifications()
        self._shift_types(provider)
        self._absence_types(provider)

        departments = self._structure(site)
        employees = self._employees(provider, work_time_models)
        self._roles(provider, employees)
        self._positions(departments)

        self.stdout.write(self.style.SUCCESS("\nFertig."))
        self.stdout.write(
            f"  Träger: {provider.name}\n"
            f"  Bereiche: {Department.objects.count()}\n"
            f"  Mitarbeitende: {Employee.objects.count()}\n"
            f"  Stellen: {Position.objects.count()}\n"
            f"  Dienstarten: {ShiftType.objects.count()}\n"
            f"  Abwesenheitsarten: {AbsenceType.objects.count()}"
        )

    # ---------------------------------------------------------------- Teile

    def _provider(self, name):
        provider = Provider.objects.first()
        if provider:
            self.stdout.write(f"Träger vorhanden: {provider.name}")
            return provider
        provider = Provider.objects.create(name=name, short_name=name[:8])
        self.stdout.write(self.style.SUCCESS(f"Träger angelegt: {provider.name}"))
        return provider

    def _site(self, provider):
        site = provider.sites.first()
        if site:
            return site

        # Adresse der ersten Gruppe als Anhaltspunkt für den Standort.
        group = Group.objects.first()
        site = Site.objects.create(
            provider=provider,
            name=group.city if group and group.city else "Hauptstandort",
            address=group.address if group else "",
            postalcode=group.postalcode if group else "",
            city=group.city if group else "",
        )
        self.stdout.write(self.style.SUCCESS(f"Standort angelegt: {site.name}"))
        return site

    def _work_time_models(self, provider):
        defaults = [
            ("Vollzeit", Decimal("39.00"), Decimal("5.0"), 30),
            ("Teilzeit 75 %", Decimal("29.25"), Decimal("4.0"), 30),
            ("Teilzeit 50 %", Decimal("19.50"), Decimal("3.0"), 30),
        ]
        models = []
        for name, hours, days, vacation in defaults:
            model, created = WorkTimeModel.objects.get_or_create(
                provider=provider,
                name=name,
                defaults={
                    "weekly_hours": hours,
                    "days_per_week": days,
                    "vacation_days": vacation,
                },
            )
            models.append(model)
            if created:
                self.stdout.write(f"  Arbeitszeitmodell: {model.name}")
        return models

    def _qualifications(self):
        for name, is_specialist in QUALIFICATIONS:
            _, created = Qualification.objects.get_or_create(
                name=name, defaults={"is_specialist": is_specialist}
            )
            if created:
                self.stdout.write(f"  Qualifikation: {name}")

    def _shift_types(self, provider):
        for name, code, start, end, pause, color, night, on_call in SHIFT_TYPES:
            _, created = ShiftType.objects.get_or_create(
                provider=provider,
                short_code=code,
                defaults={
                    "name": name,
                    "start_time": start,
                    "end_time": end,
                    "break_minutes": pause,
                    "color": color,
                    "is_night": night,
                    "is_on_call": on_call,
                },
            )
            if created:
                self.stdout.write(f"  Dienstart: {code} {name}")

    def _absence_types(self, provider):
        for name, kind, reduces, approval, color in ABSENCE_TYPES:
            _, created = AbsenceType.objects.get_or_create(
                provider=provider,
                name=name,
                defaults={
                    "kind": kind,
                    "reduces_vacation": reduces,
                    "requires_approval": approval,
                    "color": color,
                },
            )
            if created:
                self.stdout.write(f"  Abwesenheitsart: {name}")

    def _structure(self, site):
        """Je bestehender Gruppe eine Einrichtung mit einem Bereich."""
        departments = []
        for group in Group.objects.all():
            facility, _ = Facility.objects.get_or_create(
                site=site,
                name=group.name,
                defaults={"kind": "residential"},
            )
            department, created = Department.objects.get_or_create(
                facility=facility,
                name="Betreuung",
                defaults={"group": group, "minimum_staff": 1, "specialist_ratio": 50},
            )
            # Nachträglich verknüpfen, falls der Bereich schon ohne Gruppe stand.
            if department.group_id is None:
                department.group = group
                department.save(update_fields=["group"])
            departments.append(department)
            if created:
                self.stdout.write(f"  Bereich: {department}")
        return departments

    def _employees(self, provider, work_time_models):
        """Aus jedem Benutzerkonto einen Personaldatensatz ableiten."""
        full_time = work_time_models[0] if work_time_models else None
        employees = []
        for user in User.objects.all():
            employee = Employee.objects.filter(user=user).first()
            if employee:
                employees.append(employee)
                continue

            employee = Employee.objects.create(
                provider=provider,
                user=user,
                first_name=user.first_name or user.username,
                last_name=user.last_name or "",
                email=user.email,
                hired_on=user.date_joined.date(),
                work_time_model=full_time,
            )
            employees.append(employee)
            self.stdout.write(f"  Mitarbeitende: {employee.get_full_name()}")
        return employees

    def _roles(self, provider, employees):
        for employee in employees:
            if employee.roles.exists():
                continue
            # Staff wird Leitung, alle anderen Fachkraft - anpassbar im Admin.
            role = (
                "management"
                if employee.user and employee.user.is_staff
                else "specialist"
            )
            Role.objects.create(
                employee=employee,
                role=role,
                provider=provider,
                valid_from=employee.hired_on or date.today(),
            )

    def _positions(self, departments):
        """Ein schlanker Stellplan je Bereich als Ausgangspunkt."""
        blueprint = [
            ("Gruppenleitung", Decimal("1.00"), True),
            ("Pädagogische Fachkraft", Decimal("2.00"), True),
            ("Ergänzungskraft", Decimal("0.50"), False),
        ]
        for department in departments:
            if department.positions.exists():
                continue
            for title, fte, specialist in blueprint:
                Position.objects.create(
                    department=department,
                    title=title,
                    target_fte=fte,
                    requires_specialist=specialist,
                )
            self.stdout.write(f"  Stellplan angelegt für {department}")
