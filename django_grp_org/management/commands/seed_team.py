"""
Legt ein vollstaendiges Team fuer eine Gruppe an.

Eine Wohngruppe braucht genug Menschen, damit ein Monat ueberhaupt planbar
ist: rund um die Uhr besetzt, mit Ruhezeiten, Wochenenden und Urlaub. Mit
zwei Mitarbeitenden geht das nicht, und ein Dienstplan, der nur aus offenen
Stellen besteht, sagt nichts ueber die Planung aus.

Der Befehl ist wiederholbar. Wer schon da ist, wird erkannt und nicht noch
einmal angelegt; ergaenzt werden nur die fehlenden.

    python manage.py seed_team
    python manage.py seed_team --group "Campuswohngruppe 6a" --count 8

Angelegt wird jeweils: Personaldatensatz, Benutzerkonto (ohne nutzbares
Passwort - die Anmeldung richtet die Verwaltung ein), Mitgliedschaft in der
Gruppe, Arbeitszeitmodell und Qualifikation.
"""

from datetime import date

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from django_grp_backend.models import Group
from django_grp_org.defaults import ensure_qualifications, ensure_worktime_models
from django_grp_org.models import (
    Department,
    Employee,
    EmployeeQualification,
    Provider,
    Qualification,
    WorkTimeModel,
)

# Ein Team, wie es in einer Wohngruppe tatsaechlich zusammengesetzt ist:
# mehrheitlich Fachkraefte in Vollzeit, dazu Teilzeit fuer die Randzeiten und
# eine Aushilfe fuer Wochenenden. Reine Vollzeit waere leichter zu planen und
# entspraeche keiner Einrichtung, die es gibt.
TEAM = [
    # (Vorname, Nachname, Qualifikation, Arbeitszeitmodell, Leitung)
    ("Miriam", "Kaltenbach", "Sozialpädagogin / Sozialpädagoge", "Vollzeit", True),
    ("Tobias", "Ehlert", "Erzieherin / Erzieher", "Vollzeit", False),
    ("Sarah", "Wendland", "Erzieherin / Erzieher", "Vollzeit", False),
    ("Deniz", "Aktas", "Heilerziehungspflegerin / Heilerziehungspfleger", "Vollzeit", False),
    ("Katrin", "Osei", "Heilpädagogin / Heilpädagoge", "Teilzeit 75 %", False),
    ("Jonas", "Reimer", "Erzieherin / Erzieher", "Teilzeit 75 %", False),
    ("Lena", "Vosskühler", "Kinderpflegerin / Kinderpfleger", "Teilzeit 50 %", False),
    ("Ali", "Demirci", "Anerkennungspraktikum", "Geringfügige Beschäftigung", False),
]


class Command(BaseCommand):
    help = "Legt ein Team von Mitarbeitenden für eine Gruppe an."

    def add_arguments(self, parser):
        parser.add_argument(
            "--group",
            help="Name der Gruppe. Ohne Angabe: die einzige vorhandene.",
        )
        parser.add_argument(
            "--count",
            type=int,
            default=len(TEAM),
            help=(
                "Wie viele Mitarbeitende der Träger am Ende haben soll. "
                "Vorhandene zählen mit – der Befehl füllt auf, bis die Zahl "
                f"erreicht ist (höchstens {len(TEAM)} kommen aus dieser Liste)."
            ),
        )
        parser.add_argument(
            "--domain",
            default="beispiel.de",
            help="Domäne für die E-Mail-Adressen.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        gruppe = self._gruppe(options.get("group"))
        provider = self._provider()
        ziel = max(1, options["count"])
        domain = options["domain"]

        # Die Vorgabemodelle und -qualifikationen sicherstellen: das Team
        # unten nennt sie beim Namen, und wer eines geloescht hat, bekaeme
        # sonst Personen ohne Arbeitszeitmodell - und damit ohne Monatssoll,
        # nach dem die automatische Planung geht.
        ensure_worktime_models(WorkTimeModel, provider)
        ensure_qualifications(Qualification)

        bereich = Department.objects.filter(group=gruppe).first()
        if bereich is None:
            self.stdout.write(
                self.style.WARNING(
                    f"Kein Bereich zeigt auf „{gruppe.name}“. Die Personen werden "
                    "angelegt, tauchen in der Dienstplanung aber erst auf, wenn "
                    "ein Bereich auf diese Gruppe zeigt."
                )
            )

        # Wer schon da ist, zaehlt mit. "Acht Mitarbeitende" heisst acht im
        # Team, nicht acht zusaetzliche - sonst legt ein zweiter Aufruf ein
        # zweites Team an.
        vorhanden = {
            person.get_full_name().lower()
            for person in Employee.objects.filter(provider=provider)
        }
        fehlen = ziel - len(vorhanden)
        if fehlen <= 0:
            self.stdout.write(
                f"Es gibt bereits {len(vorhanden)} Mitarbeitende – nichts zu tun."
            )
            return

        neu = 0
        for vorname, nachname, qualifikation, modell, leitung in TEAM:
            if neu >= fehlen:
                break
            if f"{vorname} {nachname}".lower() in vorhanden:
                self.stdout.write(f"  vorhanden: {vorname} {nachname}")
                continue

            benutzername = self._benutzername(vorname, nachname)
            konto, _ = User.objects.get_or_create(
                username=benutzername,
                defaults={
                    "first_name": vorname,
                    "last_name": nachname,
                    "email": f"{benutzername}@{domain}",
                    "is_staff": leitung,
                },
            )
            # Kein nutzbares Passwort: die Anmeldung richtet die Verwaltung
            # ein. Ein Befehl, der Konten mit bekanntem Passwort hinterlaesst,
            # ist eine offene Tuer.
            if not konto.has_usable_password():
                konto.set_unusable_password()
                konto.save(update_fields=["password"])

            gruppe.group_members.add(konto)

            person = Employee.objects.create(
                provider=provider,
                user=konto,
                first_name=vorname,
                last_name=nachname,
                email=f"{benutzername}@{domain}",
                hired_on=date(2024, 1, 1),
                work_time_model=self._modell(modell),
                access_level="admin" if leitung else "specialist",
            )

            nachweis = Qualification.objects.filter(name=qualifikation).first()
            if nachweis:
                EmployeeQualification.objects.get_or_create(
                    employee=person, qualification=nachweis
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Qualifikation „{qualifikation}“ gibt es nicht – "
                        f"{vorname} {nachname} bleibt ohne."
                    )
                )

            neu += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"  angelegt: {vorname} {nachname} ({modell}, {qualifikation})"
                )
            )

        gesamt = Employee.objects.filter(provider=provider).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{neu} neu, {gesamt} Mitarbeitende insgesamt bei „{provider.name}“."
            )
        )

    # ------------------------------------------------------------- Helfer

    def _gruppe(self, name):
        if name:
            gruppe = Group.objects.filter(name=name).first()
            if gruppe is None:
                raise CommandError(f"Die Gruppe „{name}“ gibt es nicht.")
            return gruppe

        gruppen = list(Group.objects.all()[:2])
        if not gruppen:
            raise CommandError("Es gibt keine Gruppe. Bitte zuerst eine anlegen.")
        if len(gruppen) > 1:
            raise CommandError(
                "Es gibt mehrere Gruppen. Bitte mit --group angeben, welche gemeint ist."
            )
        return gruppen[0]

    def _provider(self):
        provider = Provider.objects.order_by("id").first()
        if provider is None:
            raise CommandError(
                "Es gibt keinen Träger. Bitte zuerst seed_organisation ausführen."
            )
        return provider

    def _modell(self, name):
        modell = WorkTimeModel.objects.filter(name=name).first()
        if modell is None:
            self.stdout.write(
                self.style.WARNING(f"  Arbeitszeitmodell „{name}“ fehlt.")
            )
        return modell

    def _benutzername(self, vorname, nachname) -> str:
        """
        Kürzel wie in der Einrichtung üblich: erster Buchstabe, Punkt, Name.

        Bei Namensgleichheit wird durchnummeriert - lieber m.mueller2 als ein
        Konto, das jemand anderem gehört.
        """
        stamm = slugify(f"{vorname[0]}.{nachname}").replace("-", ".")
        kandidat = stamm
        zaehler = 2
        while User.objects.filter(username=kandidat).exists():
            kandidat = f"{stamm}{zaehler}"
            zaehler += 1
        return kandidat
