"""
Legt einen vollständigen Demo-Träger an - erfundene Namen, keine echten Daten.

Wofür das da ist: die Wissensdatenbank auf der Startseite zeigt Bildschirm-
fotos aus der laufenden Anwendung. Damit die reproduzierbar bleiben und dabei
keine Bewohner- oder Personaldaten einer Einrichtung nach draußen geraten,
entsteht der Bestand hier aus einer festen Liste erfundener Namen.

    python manage.py seed_demo --passwort 'ein-langes-passwort'

Der Befehl ist wiederholbar und ergänzt, was fehlt. Er läuft auch auf einer
Installation, die gerade erst durch den Einrichtungsassistenten gegangen ist:
Träger, erste Gruppe und erstes Konto erkennt er wieder, statt sie ein
zweites Mal danebenzustellen.

Nichts daran gehört in den Betrieb - der Befehl legt Personen an, die es
nicht gibt. Ohne `--passwort` rührt er kein Passwort an; ein Befehl, der
Konten mit bekanntem Passwort hinterlässt, ist eine offene Tür.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from django_grp_backend.models import (
    Group,
    Protocol,
    ProtocolAttendance,
    ProtocolItem,
    ProtocolObservation,
    ProtocolPresence,
    ProtocolTemplate,
    ProtocolTodo,
    Resident,
    ResidentContact,
)
from django_grp_care.models import (
    CaseFile,
    CaseMeeting,
    CaseParticipant,
    HelpGoal,
    HelpMeasure,
    HelpPlan,
)
from django_grp_duty.autofill import autofill_plan
from django_grp_duty.models import (
    Absence,
    AbsenceType,
    DutyPlan,
    ShiftPreference,
    ShiftType,
    StaffingRequirement,
    TimeEntry,
)
from django_grp_duty.services import generate_shifts
from django_grp_org.defaults import (
    ensure_absence_types,
    ensure_qualifications,
    ensure_shift_types,
    ensure_worktime_models,
)
from django_grp_org.models import (
    Contract,
    Department,
    Employee,
    EmployeeQualification,
    Facility,
    Provider,
    Qualification,
    Role,
    Site,
    WorkTimeModel,
)

TRAEGER = "Wegzeichen Jugendhilfe gGmbH"
EINRICHTUNG = "Haus Ahornallee"
ORT = ("Ahornallee 14", "31655", "Talheim")
DOMAENE = "wegzeichen.example"

# Zwei Wohngruppen, damit in den Bildern sichtbar wird, wozu die Farbe an der
# Gruppe gut ist: bei einer einzelnen gibt es nichts zu unterscheiden.
GRUPPEN = [
    {
        "name": "Wohngruppe Ahorn",
        "kuerzel": "AH",
        "farbe": "#abc270",
        "adresse": "Ahornallee 14",
        "plz": "31655",
        "ort": "Talheim",
    },
    {
        "name": "Wohngruppe Birke",
        "kuerzel": "BI",
        "farbe": "#fda769",
        "adresse": "Birkenweg 3",
        "plz": "31655",
        "ort": "Talheim",
    },
]

# (Vorname, Nachname, Qualifikation, Arbeitszeitmodell, Zugriff, Gruppe)
#
# Mehrheitlich Fachkräfte in Vollzeit, dazu Teilzeit für die Randzeiten und
# zwei Aushilfen. Reine Vollzeit wäre leichter zu planen und entspräche keiner
# Einrichtung, die es gibt - im Dienstplan sähe man dann auch nicht, wozu das
# Monatssoll gut ist.
TEAM = [
    ("Miriam", "Kaltenbach", "Sozialpädagogin / Sozialpädagoge", "Vollzeit", "admin", 0),
    ("Tobias", "Ehlert", "Erzieherin / Erzieher", "Vollzeit", "specialist", 0),
    ("Sarah", "Wendland", "Erzieherin / Erzieher", "Vollzeit", "specialist", 0),
    (
        "Deniz",
        "Aktas",
        "Heilerziehungspflegerin / Heilerziehungspfleger",
        "Vollzeit",
        "specialist",
        0,
    ),
    ("Katrin", "Osei", "Heilpädagogin / Heilpädagoge", "Teilzeit 75 %", "specialist", 0),
    ("Jonas", "Reimer", "Erzieherin / Erzieher", "Teilzeit 75 %", "specialist", 0),
    (
        "Lena",
        "Vosskühler",
        "Kinderpflegerin / Kinderpfleger",
        "Teilzeit 50 %",
        "assistant",
        0,
    ),
    (
        "Ali",
        "Demirci",
        "Anerkennungspraktikum",
        "Geringfügige Beschäftigung",
        "assistant",
        0,
    ),
    ("Frauke", "Neidhart", "Erzieherin / Erzieher", "Vollzeit", "specialist", 1),
    (
        "Samuel",
        "Okonkwo",
        "Sozialarbeiterin / Sozialarbeiter",
        "Vollzeit",
        "specialist",
        1,
    ),
    ("Pia", "Hollstein", "Erzieherin / Erzieher", "Teilzeit 75 %", "specialist", 1),
    (
        "Nils",
        "Ackermann",
        "Heilerziehungspflegerin / Heilerziehungspfleger",
        "Vollzeit",
        "specialist",
        1,
    ),
]

# (Vorname, Nachname, Gruppe, eingezogen vor Tagen, Alter, Geschlecht)
#
# Alter und Geschlecht braucht die amtliche Statistik nach § 99 SGB VIII.
# Eine Person bleibt ohne beides - "ohne Angabe" ist dort eine zulaessige
# Auspraegung, und die Bildschirmfotos sollen zeigen, wie das aussieht.
BEWOHNER = [
    ("Nele", "Brandhorst", 0, 420, 14, "female"),
    ("Yusuf", "Kaya", 0, 260, 16, "male"),
    ("Lina", "Wegener", 0, 180, 13, "female"),
    ("Tim", "Ostermann", 0, 95, 15, "male"),
    ("Amira", "Nasser", 0, 40, 12, "female"),
    ("Jonas", "Kirchhoff", 1, 610, 17, "male"),
    ("Mia", "Sonntag", 1, 300, 15, "female"),
    ("Elias", "Bertram", 1, 150, 14, "diverse"),
    ("Sophie", "Lindqvist", 1, 70, 16, ""),
]

# Kontakte für die ersten vier - mehr braucht kein Bildschirmfoto, und jede
# Zeile mehr ist eine Zeile, die gepflegt sein will.
KONTAKTE = {
    "Nele Brandhorst": [
        ("mother", "Andrea Brandhorst", "Mutter", "05121 449022", "", True, True),
        (
            "youth_office",
            "Jugendamt Talheim",
            "Fallführung",
            "05121 400180",
            "kjhd@talheim.example",
            False,
            False,
        ),
        (
            "school",
            "Gesamtschule Am Mühlenberg",
            "Klassenleitung",
            "05121 447700",
            "",
            False,
            False,
        ),
    ],
    "Yusuf Kaya": [
        ("custodian", "Bernd Achterberg", "Vormund", "0511 2280455", "", True, True),
        (
            "therapy",
            "Praxis am Marktplatz",
            "Kinder- und Jugendpsychiatrie",
            "05121 448811",
            "",
            False,
            False,
        ),
    ],
    "Lina Wegener": [
        ("mother", "Katja Wegener", "Mutter", "0170 5540221", "", True, True),
        ("father", "Markus Wegener", "Vater", "0171 3390118", "", True, False),
    ],
    "Tim Ostermann": [
        (
            "guardian",
            "Silke Ostermann",
            "Mutter, alleinsorgeberechtigt",
            "05121 776540",
            "",
            True,
            True,
        ),
    ],
}


class Command(BaseCommand):
    help = "Legt einen Demo-Träger mit erfundenen Namen an (für Bildschirmfotos)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--passwort",
            default="",
            help=(
                "Passwort für das Konto m.kaltenbach. Ohne Angabe bleibt das "
                "vorhandene Passwort unangetastet."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.heute = timezone.localdate()

        traeger = self._traeger()
        einrichtung = self._einrichtung(traeger)
        self._stammdaten(traeger)

        gruppen = self._gruppen()
        bereiche = self._bereiche(einrichtung, gruppen)
        self._besetzungsvorgaben(traeger, bereiche)

        personen = self._personal(traeger, gruppen)
        bewohner = self._bewohner(gruppen)
        self._kontakte(bewohner)

        self._protokolle(gruppen, bewohner)
        self._dienstplaene(traeger, bereiche)
        self._abwesenheiten(traeger, personen)
        self._zeiten(personen)
        self._wuensche(traeger, personen)
        self._hilfeplanung(traeger, bewohner, personen)

        self._passwort(options["passwort"])
        self._bilanz(traeger)

    # ------------------------------------------------------------ Organisation

    def _traeger(self):
        traeger = Provider.objects.filter(name=TRAEGER).first() or Provider.objects.first()
        if traeger is None:
            traeger = Provider.objects.create(name=TRAEGER)
        # Der Einrichtungsassistent fragt das Kürzel nicht ab. Es steht in der
        # Kopfzeile jedes PDF-Exports, also gehört es nachgetragen.
        felder = []
        if not traeger.short_name:
            traeger.short_name = "Wegzeichen"
            felder.append("short_name")
        for feld, wert in (("address", ORT[0]), ("postalcode", ORT[1]), ("city", ORT[2])):
            if not getattr(traeger, feld):
                setattr(traeger, feld, wert)
                felder.append(feld)
        if felder:
            traeger.save(update_fields=felder)
        self.stdout.write(f"Träger: {traeger.name}")
        return traeger

    def _einrichtung(self, traeger):
        standort = traeger.sites.first()
        if standort is None:
            standort = Site.objects.create(
                provider=traeger,
                name=EINRICHTUNG,
                address=ORT[0],
                postalcode=ORT[1],
                city=ORT[2],
            )
        einrichtung = standort.facilities.first()
        if einrichtung is None:
            einrichtung = Facility.objects.create(
                site=standort, name=EINRICHTUNG, kind="residential"
            )
        return einrichtung

    def _stammdaten(self, traeger):
        ensure_qualifications(Qualification)
        ensure_worktime_models(WorkTimeModel, traeger)
        ensure_shift_types(ShiftType, traeger)
        ensure_absence_types(AbsenceType, traeger)

    def _gruppen(self):
        gruppen = []
        for eintrag in GRUPPEN:
            gruppe, _ = Group.objects.get_or_create(
                name=eintrag["name"],
                defaults={
                    "short_name": eintrag["kuerzel"],
                    "color": eintrag["farbe"],
                    "address": eintrag["adresse"],
                    "postalcode": eintrag["plz"],
                    "city": eintrag["ort"],
                },
            )
            felder = []
            if not gruppe.short_name:
                gruppe.short_name = eintrag["kuerzel"]
                felder.append("short_name")
            if not gruppe.address:
                gruppe.address = eintrag["adresse"]
                gruppe.postalcode = eintrag["plz"]
                gruppe.city = eintrag["ort"]
                felder += ["address", "postalcode", "city"]
            if felder:
                gruppe.save(update_fields=felder)
            gruppen.append(gruppe)
        return gruppen

    def _bereiche(self, einrichtung, gruppen):
        bereiche = []
        for gruppe in gruppen:
            bereich = Department.objects.filter(group=gruppe).first()
            if bereich is None:
                bereich, _ = Department.objects.get_or_create(
                    facility=einrichtung,
                    name=gruppe.name,
                    defaults={"minimum_staff": 2, "specialist_ratio": 50},
                )
            if bereich.group_id is None:
                bereich.group = gruppe
                bereich.save(update_fields=["group"])
            bereiche.append(bereich)
        return bereiche

    def _besetzungsvorgaben(self, traeger, bereiche):
        """
        Was der Bereich wann braucht.

        Ohne diese Zeilen prüft die Regelprüfung gegen eine einzige Tageszahl
        für den ganzen Tag. Das reicht in einer Wohngruppe nicht: nachts
        genügt eine Bereitschaft, am Nachmittag braucht es zwei.
        """
        arten = {a.short_code: a for a in ShiftType.objects.filter(provider=traeger)}
        vorgaben = [("F", 1, 1), ("Z", 1, 1), ("S", 2, 1), ("N", 1, 0)]
        for bereich in bereiche:
            for kuerzel, personen, fachkraefte in vorgaben:
                art = arten.get(kuerzel)
                if art is None:
                    continue
                StaffingRequirement.objects.get_or_create(
                    department=bereich,
                    shift_type=art,
                    defaults={
                        "minimum_staff": personen,
                        "minimum_specialists": fachkraefte,
                    },
                )

    # ---------------------------------------------------------------- Personal

    def _personal(self, traeger, gruppen):
        modelle = {m.name: m for m in WorkTimeModel.objects.filter(provider=traeger)}
        nachweise = {q.name: q for q in Qualification.objects.all()}
        personen = []

        for nummer, eintrag in enumerate(TEAM, start=1):
            vorname, nachname, qualifikation, modell, zugriff, index = eintrag
            benutzername = f"{vorname[0].lower()}.{self._schlicht(nachname)}"
            adresse = f"{benutzername}@{DOMAENE}"

            konto, _ = User.objects.get_or_create(
                username=benutzername,
                defaults={
                    "first_name": vorname,
                    "last_name": nachname,
                    "email": adresse,
                    "is_staff": zugriff == "admin",
                    "is_superuser": zugriff == "admin",
                },
            )
            # Kein nutzbares Passwort für die übrigen Konten - wer sich damit
            # anmelden können soll, bekommt es über die Verwaltung.
            if not konto.has_usable_password():
                konto.set_unusable_password()
                konto.save(update_fields=["password"])

            gruppen[index].group_members.add(konto)

            person = Employee.objects.filter(user=konto).first()
            if person is None:
                person = Employee.objects.create(
                    provider=traeger,
                    user=konto,
                    first_name=vorname,
                    last_name=nachname,
                    email=adresse,
                    access_level=zugriff,
                    hired_on=self.heute - timedelta(days=300 + nummer * 47),
                )

            felder = []
            if not person.personnel_number:
                person.personnel_number = f"P-{1000 + nummer}"
                felder.append("personnel_number")
            if not person.phone:
                person.phone = f"05121 4490{nummer:02d}"
                felder.append("phone")
            # Ohne Arbeitszeitmodell hat die Person kein Monatssoll, und der
            # Automat weiss nicht, wen er als Nächstes einteilen soll.
            if person.work_time_model_id is None and modell in modelle:
                person.work_time_model = modelle[modell]
                felder.append("work_time_model")
            if felder:
                person.save(update_fields=felder)

            nachweis = nachweise.get(qualifikation)
            if nachweis:
                EmployeeQualification.objects.get_or_create(
                    employee=person,
                    qualification=nachweis,
                    defaults={"acquired_on": person.hired_on},
                )
            if not person.contracts.exists():
                Contract.objects.create(
                    employee=person,
                    valid_from=person.hired_on,
                    kind="minijob" if modell.startswith("Gering") else "permanent",
                    weekly_hours=(
                        modelle[modell].weekly_hours
                        if modell in modelle
                        else Decimal("39.00")
                    ),
                    pay_grade="S 3" if zugriff == "assistant" else "S 8b",
                )
            if not person.roles.exists():
                Role.objects.create(
                    employee=person,
                    provider=traeger,
                    role={
                        "admin": "management",
                        "specialist": "specialist",
                        "assistant": "assistant",
                    }[zugriff],
                    valid_from=person.hired_on,
                )
            personen.append(person)

        self.stdout.write(f"  Personal: {len(personen)}")
        return personen

    # ---------------------------------------------------------------- Bewohner

    def _bewohner(self, gruppen):
        bewohner = []
        for vorname, nachname, index, seit, alter, geschlecht in BEWOHNER:
            person, _ = Resident.objects.get_or_create(
                first_name=vorname,
                last_name=nachname,
                group=gruppen[index],
                defaults={"moved_in_since": self.heute - timedelta(days=seit)},
            )
            # Ein Geburtstag mitten im Jahr, damit das gerechnete Alter nicht
            # am Stichtag kippt, waehrend jemand die Bilder ansieht.
            felder = []
            if person.birth_date is None and alter:
                person.birth_date = date(self.heute.year - alter, 6, 15)
                felder.append("birth_date")
            if not person.gender and geschlecht:
                person.gender = geschlecht
                felder.append("gender")
            if felder:
                person.save(update_fields=felder)
            bewohner.append(person)
        self.stdout.write(f"  Bewohner: {len(bewohner)}")
        return bewohner

    def _kontakte(self, bewohner):
        nach_name = {f"{b.first_name} {b.last_name}": b for b in bewohner}
        for name, eintraege in KONTAKTE.items():
            person = nach_name.get(name)
            if person is None:
                continue
            for platz, zeile in enumerate(eintraege):
                rolle, kontakt, bezug, telefon, mail, sorge, notfall = zeile
                ResidentContact.objects.get_or_create(
                    resident=person,
                    name=kontakt,
                    defaults={
                        "kind": rolle,
                        "relationship": bezug,
                        "phone": telefon,
                        "email": mail,
                        "has_custody": sorge,
                        "is_emergency": notfall,
                        "position": platz,
                    },
                )

    # -------------------------------------------------------------- Protokolle

    def _protokolle(self, gruppen, bewohner):
        """
        Drei Protokolle je Gruppe - exportiert, bereit, Entwurf.

        Die Statuskette ist das, was die Anleitung erklärt. Ein Bildschirmfoto,
        auf dem alle drei Protokolle "Entwurf" sind, erklärt davon nichts.
        """
        vorlage = (
            ProtocolTemplate.objects.filter(name__icontains="Gruppenabend").first()
            or ProtocolTemplate.objects.first()
        )

        for gruppe in gruppen:
            gruppen_bewohner = [b for b in bewohner if b.group_id == gruppe.id]
            konten = list(gruppe.group_members.all())

            for tage, status in ((21, "exported"), (7, "ready"), (1, "draft")):
                protokoll, neu = Protocol.objects.get_or_create(
                    group=gruppe,
                    protocol_date=self.heute - timedelta(days=tage),
                    defaults={
                        "status": status,
                        "template": vorlage,
                        "topic": "Gruppenabend",
                    },
                )
                if neu:
                    self._protokoll_inhalt(protokoll, gruppen_bewohner, konten)

        self.stdout.write(f"  Protokolle: {Protocol.objects.count()}")

    def _protokoll_inhalt(self, protokoll, bewohner, konten):
        punkte = [
            (
                "Rückblick auf die Woche",
                "text",
                "Die Woche verlief ruhig. Der Ausflug am Samstag zum Kletterwald "
                "wurde von allen mitgetragen, Rückfahrt planmäßig um 18 Uhr.",
                None,
            ),
            (
                "Absprachen",
                "table",
                None,
                {
                    "columns": ["Was", "Wer", "Bis wann"],
                    "rows": [
                        ["Küchendienst neu einteilen", "Tobias Ehlert", "Freitag"],
                        [
                            "Fahrräder zur Werkstatt bringen",
                            "Lena Vosskühler",
                            "nächste Woche",
                        ],
                        ["Elterngespräch terminieren", "Miriam Kaltenbach", "Monatsende"],
                    ],
                },
            ),
            (
                "Hausregeln",
                "text",
                "Die Bildschirmzeit am Wochenende bleibt bei zwei Stunden. Die "
                "Gruppe hat für eine Verlängerung gestimmt; das Team bleibt "
                "vorerst bei der Regel und prüft sie in vier Wochen erneut.",
                None,
            ),
            (
                "Verschiedenes",
                "text",
                "Der Wäschetrockner ist repariert. Den Zahnarzttermin am 14. "
                "begleitet der Frühdienst.",
                None,
            ),
        ]
        for platz, (name, art, text, daten) in enumerate(punkte):
            ProtocolItem.objects.create(
                protocol=protokoll,
                name=name,
                position=platz,
                kind=art,
                value=text,
                data=daten,
            )

        aufgaben = [
            ("Küchendienstplan aushängen", "Tobias Ehlert", 3),
            ("Fahrräder zur Werkstatt bringen", "Lena Vosskühler", 9),
            ("Elterngespräch vereinbaren", "Miriam Kaltenbach", 16),
        ]
        for platz, (was, wer, in_tagen) in enumerate(aufgaben):
            faellig = datetime.combine(
                protokoll.protocol_date + timedelta(days=in_tagen), time(18, 0)
            )
            ProtocolTodo.objects.create(
                protocol=protokoll,
                what=was,
                who=wer,
                when=timezone.make_aware(faellig),
                position=platz,
            )

        # Die Anwesenheitsliste des Teams legt das Protokoll beim Speichern
        # selbst an - hier wird nur noch eingetragen, wer dabei war.
        for platz, konto in enumerate(konten):
            ProtocolPresence.objects.update_or_create(
                protocol=protokoll,
                user=konto,
                defaults={"was_present": platz < 3},
            )

        for platz, person in enumerate(bewohner):
            ProtocolAttendance.objects.update_or_create(
                protocol=protokoll,
                resident=person,
                defaults={
                    "was_present": platz != 1,
                    "note": "" if platz != 1 else "Bei der Großmutter",
                },
            )

        if bewohner:
            ProtocolObservation.objects.create(
                protocol=protokoll,
                category="course",
                position=0,
                text=(
                    "Die Gruppe hat den Ausflug gemeinsam vorbereitet und die "
                    "Aufgaben ohne Aufforderung untereinander verteilt."
                ),
            )
            ProtocolObservation.objects.create(
                protocol=protokoll,
                resident=bewohner[0],
                category="observation",
                position=1,
                text=(
                    "Bringt sich in der Runde deutlich häufiger ein als noch im "
                    "Vormonat und hält die Absprache zur Hausaufgabenzeit ein."
                ),
            )

    # -------------------------------------------------------------- Dienstplan

    def _dienstplaene(self, traeger, bereiche):
        """
        Vormonat abgeschlossen, laufender Monat veröffentlicht, Folgemonat Entwurf.

        Drei Stände nebeneinander, weil die Anleitung genau diesen Unterschied
        erklärt: ein Entwurf ist für das Team nicht sichtbar.
        """
        arten = list(ShiftType.objects.filter(provider=traeger))
        monate = [
            (self._monat(-1), "locked"),
            (self._monat(0), "published"),
            (self._monat(1), "draft"),
        ]
        for bereich in bereiche:
            for (jahr, monat), status in monate:
                plan, neu = DutyPlan.objects.get_or_create(
                    department=bereich,
                    year=jahr,
                    month=monat,
                    defaults={"status": status},
                )
                if not neu:
                    continue
                generate_shifts(plan, arten)
                autofill_plan(plan)

        dienste = sum(plan.shifts.count() for plan in DutyPlan.objects.all())
        self.stdout.write(f"  Dienstpläne: {DutyPlan.objects.count()} mit {dienste} Diensten")

    def _monat(self, versatz: int) -> tuple[int, int]:
        jahr, monat = self.heute.year, self.heute.month + versatz
        while monat < 1:
            monat += 12
            jahr -= 1
        while monat > 12:
            monat -= 12
            jahr += 1
        return jahr, monat

    def _abwesenheiten(self, traeger, personen):
        arten = {a.name: a for a in AbsenceType.objects.filter(provider=traeger)}
        eintraege = [
            (1, "Urlaub", 12, 19, "approved"),
            (2, "Krankheit", -3, -1, "approved"),
            (4, "Fortbildung", 26, 27, "requested"),
            (6, "Urlaub", 33, 44, "requested"),
            (9, "Urlaub", 5, 12, "approved"),
        ]
        for index, art, von, bis, status in eintraege:
            if index >= len(personen) or art not in arten:
                continue
            Absence.objects.get_or_create(
                employee=personen[index],
                absence_type=arten[art],
                start_date=self.heute + timedelta(days=von),
                defaults={
                    "end_date": self.heute + timedelta(days=bis),
                    "status": status,
                },
            )

    def _zeiten(self, personen):
        """Buchungen der letzten zehn Tage, damit das Zeitkonto nicht bei null steht."""
        for versatz in range(1, 11):
            tag = self.heute - timedelta(days=versatz)
            for person in personen[:4]:
                TimeEntry.objects.get_or_create(
                    employee=person,
                    date=tag,
                    start_time=time(6, 30),
                    defaults={
                        "end_time": time(14, 30),
                        "break_minutes": 30,
                        "category": "work",
                        "approved": versatz > 3,
                    },
                )

    def _wuensche(self, traeger, personen):
        arten = {a.short_code: a for a in ShiftType.objects.filter(provider=traeger)}
        eintraege = [
            (1, 9, "F", "wish", "Fährt danach zum Chor"),
            (2, 11, None, "unavailable", "Umzug"),
            (3, 14, "N", "block", ""),
        ]
        for index, in_tagen, kuerzel, art, notiz in eintraege:
            if index >= len(personen):
                continue
            ShiftPreference.objects.get_or_create(
                employee=personen[index],
                date=self.heute + timedelta(days=in_tagen),
                defaults={
                    "shift_type": arten.get(kuerzel) if kuerzel else None,
                    "kind": art,
                    "note": notiz,
                },
            )

    # ------------------------------------------------------------ Hilfeplanung

    def _hilfeplanung(self, traeger, bewohner, personen):
        fallfuehrung = ["Ines Warnke", "Bernd Achterberg", "Ines Warnke", "Cem Yildirim"]
        leitung = personen[0].get_full_name() if personen else "Bezugsbetreuung"

        for platz, person in enumerate(bewohner[:4]):
            akte, neu = CaseFile.objects.get_or_create(
                resident=person,
                defaults={
                    "provider": traeger,
                    "case_number": f"JA-{self.heute.year}-{4100 + platz}",
                    "youth_office": "Jugendamt Talheim",
                    "case_manager": fallfuehrung[platz],
                    "opened_on": person.moved_in_since,
                    "status": "open",
                },
            )
            if not neu:
                continue

            CaseParticipant.objects.create(
                case_file=akte,
                kind="youth_office",
                name=akte.case_manager,
                organisation="Jugendamt Talheim",
                contact="05121 400180",
            )
            CaseParticipant.objects.create(
                case_file=akte,
                kind="facility",
                name=leitung,
                organisation=TRAEGER,
                contact="05121 449001",
            )

            plan = HelpPlan.objects.create(
                case_file=akte,
                version=1,
                legal_basis="34",
                help_form="Stationäre Wohngruppe",
                valid_from=person.moved_in_since,
                valid_to=person.moved_in_since + timedelta(days=365),
                status="active",
                situation=(
                    "Aufnahme nach einer Krisenunterbringung. Die Beschulung war "
                    "über mehrere Monate unterbrochen. Der Kontakt zur Herkunfts"
                    "familie besteht und wird begleitet fortgeführt."
                ),
                review_date=person.moved_in_since + timedelta(days=180),
            )
            ziele = [
                ("Regelmäßiger Schulbesuch", "school", "in_progress", "wöchentlich"),
                (
                    "Tagesstruktur eigenständig einhalten",
                    "independence",
                    "open",
                    "täglich",
                ),
                ("Begleiteter Kontakt zur Familie", "family", "in_progress", "monatlich"),
            ]
            for stelle, (titel, kategorie, stand, takt) in enumerate(ziele):
                ziel = HelpGoal.objects.create(
                    help_plan=plan,
                    title=titel,
                    category=kategorie,
                    status=stand,
                    target_date=self.heute + timedelta(days=120),
                    position=stelle,
                )
                HelpMeasure.objects.create(
                    goal=ziel,
                    title=f"Bezugsbetreuungsgespräch ({takt})",
                    responsible="Bezugsbetreuung",
                    position=0,
                )

            CaseMeeting.objects.create(
                case_file=akte,
                help_plan=plan,
                kind="help_plan",
                date=person.moved_in_since + timedelta(days=30),
                location="Jugendamt Talheim",
                participants="Jugendamt, Sorgeberechtigte, Bezugsbetreuung, Jugendliche:r",
                minutes="Ausgangslage besprochen, Ziele abgestimmt.",
                decisions="Die Hilfe wird für zwölf Monate fortgeschrieben.",
                next_meeting=person.moved_in_since + timedelta(days=210),
            )

    # ----------------------------------------------------------------- Abschluss

    def _passwort(self, passwort: str):
        if not passwort:
            return
        konto = User.objects.filter(username="m.kaltenbach").first()
        if konto is None:
            return
        konto.set_password(passwort)
        konto.save(update_fields=["password"])
        self.stdout.write(self.style.SUCCESS("  Passwort für m.kaltenbach gesetzt."))

    def _bilanz(self, traeger):
        self.stdout.write(self.style.SUCCESS("\nFertig."))
        self.stdout.write(
            f"  Träger:      {traeger.name}\n"
            f"  Gruppen:     {Group.objects.count()}\n"
            f"  Bewohner:    {Resident.objects.count()}\n"
            f"  Personal:    {Employee.objects.count()}\n"
            f"  Protokolle:  {Protocol.objects.count()}\n"
            f"  Dienstpläne: {DutyPlan.objects.count()}\n"
            f"  Fallakten:   {CaseFile.objects.count()}"
        )

    @staticmethod
    def _schlicht(text: str) -> str:
        """Nachname als Benutzername: Umlaute ausgeschrieben, sonst nur Buchstaben."""
        klein = text.lower()
        for zeichen, ziel in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
            klein = klein.replace(zeichen, ziel)
        return "".join(c for c in klein if c.isalnum())
