"""
Organisationsstruktur und Personalstammdaten.

Deckt Phase 0 (Mandanten- und Rollenmodell) und Phase 1 (Stammdaten und
Organisation) der Roadmap ab. Alle folgenden Module - Dienstplanung,
Abwesenheiten, Zeiterfassung, Hilfeplanung - bauen darauf auf.

Hinweis zu db_constraint=False: Das Datenverzeichnis des Entwicklungs-
Containers liegt auf einem Windows-Bind-Mount (utils/docker-compose.yml).
InnoDB kann dort keine Dateien umbenennen, wodurch jedes
"ALTER TABLE ... ADD FOREIGN KEY" abbricht. Django prueft die Beziehungen
weiterhin. Laeuft die Datenbank auf einem Docker-Volume, kann das entfallen.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


def fk(to, **kwargs):
    """ForeignKey ohne Datenbank-Constraint - siehe Modulkommentar."""
    kwargs.setdefault("on_delete", models.CASCADE)
    kwargs["db_constraint"] = False
    return models.ForeignKey(to, **kwargs)


# ============================================================ Phase 0


class Provider(models.Model):
    """
    Traeger - die oberste Ebene und zugleich der Mandant.

    Alles Weitere haengt an einem Traeger, damit mehrere Organisationen
    dieselbe Installation nutzen koennen, ohne einander zu sehen.
    """

    name = models.CharField(max_length=150, verbose_name="Name")
    short_name = models.CharField(
        max_length=30, blank=True, default="", verbose_name="Kürzel"
    )
    address = models.CharField(max_length=150, blank=True, default="")
    postalcode = models.CharField(max_length=10, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Träger"
        verbose_name_plural = "Träger"

    def __str__(self) -> str:
        return self.name


class Site(models.Model):
    """Standort eines Traegers."""

    provider = fk(Provider, related_name="sites", verbose_name="Träger")
    name = models.CharField(max_length=150, verbose_name="Name")
    address = models.CharField(max_length=150, blank=True, default="")
    postalcode = models.CharField(max_length=10, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["provider", "name"]
        verbose_name = "Standort"
        verbose_name_plural = "Standorte"

    def __str__(self) -> str:
        return f"{self.name} ({self.provider.name})"


class Facility(models.Model):
    """Einrichtung - die Betriebseinheit, unter der die Gruppen haengen."""

    KIND_CHOICES = [
        ("residential", "Wohngruppe (stationär)"),
        ("day", "Tagesgruppe (teilstationär)"),
        ("outpatient", "Ambulantes Angebot"),
        ("administration", "Verwaltung"),
    ]

    site = fk(Site, related_name="facilities", verbose_name="Standort")
    name = models.CharField(max_length=150, verbose_name="Name")
    kind = models.CharField(
        max_length=20,
        choices=KIND_CHOICES,
        default="residential",
        verbose_name="Art",
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")

    class Meta:
        ordering = ["site", "name"]
        verbose_name = "Einrichtung"
        verbose_name_plural = "Einrichtungen"

    def __str__(self) -> str:
        return self.name


class Department(models.Model):
    """
    Bereich innerhalb einer Einrichtung.

    Hier haengt der Stellplan, und hier werden die Wohn- und Tagesgruppen aus
    django_grp_backend eingeordnet.
    """

    facility = fk(Facility, related_name="departments", verbose_name="Einrichtung")
    name = models.CharField(max_length=150, verbose_name="Name")
    group = fk(
        "django_grp_backend.Group",
        related_name="departments",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="Gruppe",
        help_text="Verknüpfung zur Wohn-/Tagesgruppe, sofern vorhanden",
    )
    minimum_staff = models.PositiveIntegerField(
        default=1,
        verbose_name="Mindestbesetzung",
        help_text="Wie viele Personen müssen im Dienst gleichzeitig anwesend sein",
    )
    specialist_ratio = models.PositiveIntegerField(
        default=50,
        verbose_name="Fachkraftquote in Prozent",
        help_text="Anteil der Dienststunden, der von Fachkräften geleistet werden muss",
    )

    class Meta:
        ordering = ["facility", "name"]
        verbose_name = "Bereich"
        verbose_name_plural = "Bereiche"

    def __str__(self) -> str:
        return f"{self.facility.name} / {self.name}"


class Role(models.Model):
    """
    Rolle einer Person in der Organisation.

    Die Rolle gilt jeweils auf der Ebene, die gesetzt ist: nur Traeger =
    traegerweit, mit Einrichtung = dort, mit Bereich = nur in diesem Bereich.

    Das ist die organisatorische Funktion - Grundlage fuer Stellenplan und
    Fachkraftquote. Was jemand in der Software darf, steht dagegen in
    Employee.access_level.
    """

    ROLE_CHOICES = [
        ("management", "Leitung"),
        ("specialist", "Fachkraft"),
        ("assistant", "Ergänzungskraft"),
        ("administration", "Verwaltung"),
        ("youth_office", "Jugendamt (Lesezugriff)"),
    ]

    employee = fk("Employee", related_name="roles", verbose_name="Mitarbeitende")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, verbose_name="Rolle")
    provider = fk(Provider, related_name="roles", verbose_name="Träger")
    facility = fk(
        Facility,
        related_name="roles",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="Einrichtung",
    )
    department = fk(
        Department,
        related_name="roles",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="Bereich",
    )
    valid_from = models.DateField(verbose_name="Gültig ab")
    valid_to = models.DateField(blank=True, null=True, verbose_name="Gültig bis")

    class Meta:
        ordering = ["employee", "role"]
        verbose_name = "Rolle"
        verbose_name_plural = "Rollen"

    def __str__(self) -> str:
        scope = self.department or self.facility or self.provider
        return f"{self.employee} – {self.get_role_display()} ({scope})"


# ============================================================ Phase 1


class Qualification(models.Model):
    """Abschluss oder Zusatzqualifikation."""

    name = models.CharField(max_length=120, unique=True, verbose_name="Bezeichnung")
    is_specialist = models.BooleanField(
        default=True,
        verbose_name="Fachkraftqualifikation",
        help_text="Zählt für die Fachkraftquote",
    )
    description = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["name"]
        verbose_name = "Qualifikation"
        verbose_name_plural = "Qualifikationen"

    def __str__(self) -> str:
        return self.name


class WorkTimeModel(models.Model):
    """Arbeitszeitmodell - Grundlage fuer Soll-Stunden und Zeitkonten."""

    provider = fk(Provider, related_name="work_time_models", verbose_name="Träger")
    name = models.CharField(max_length=120, verbose_name="Bezeichnung")
    weekly_hours = models.DecimalField(
        max_digits=5, decimal_places=2, verbose_name="Wochenstunden"
    )
    days_per_week = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        default=Decimal("5.0"),
        verbose_name="Tage pro Woche",
    )
    vacation_days = models.PositiveIntegerField(
        default=30, verbose_name="Urlaubstage pro Jahr"
    )
    notes = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["provider", "name"]
        verbose_name = "Arbeitszeitmodell"
        verbose_name_plural = "Arbeitszeitmodelle"

    def __str__(self) -> str:
        return f"{self.name} ({self.weekly_hours} h)"


class Employee(models.Model):
    """
    Eine Person - Personaldatensatz und Zugang in einem.

    Frueher waren das zwei Dinge: Personalakte hier, Benutzerkonto dort.
    Das hiess, jede Person zweimal anzulegen und die beiden Listen von Hand
    zusammenzuhalten. Jetzt ist der Personaldatensatz die Person, `user`
    ihr Zugang und `role` das, was sie darf.

    Der Zugang bleibt optional (`user` darf leer sein): eine Person kann
    ausscheiden und ihr Konto verlieren, waehrend die Personaldaten aus
    Aufbewahrungsgruenden bleiben.
    """

    # Was die Person in der Software darf. Nicht zu verwechseln mit dem
    # Modell Role weiter oben: das ist die organisatorische Funktion mit
    # Geltungsbereich und Zeitraum, Grundlage des Stellenplans. Hier geht
    # es allein um Zugriff, und davon hat eine Person genau einen.
    ACCESS_CHOICES = [
        ("admin", "Mitarbeiter"),
        ("specialist", "Fachkraft"),
        ("assistant", "Aushilfe / Azubi"),
    ]

    provider = fk(Provider, related_name="employees", verbose_name="Träger")
    access_level = models.CharField(
        max_length=20,
        choices=ACCESS_CHOICES,
        default="specialist",
        verbose_name="Zugriff",
        help_text=(
            "Mitarbeiter: verwaltet Stammdaten, Personal und Dienstplan. "
            "Fachkraft: schreibt in den eigenen Gruppen. "
            "Aushilfe / Azubi: liest in den eigenen Gruppen."
        ),
    )
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="employee",
        db_constraint=False,
        verbose_name="Systemkonto",
    )
    personnel_number = models.CharField(
        max_length=30, blank=True, default="", verbose_name="Personalnummer"
    )
    first_name = models.CharField(max_length=100, verbose_name="Vorname")
    last_name = models.CharField(max_length=100, verbose_name="Nachname")
    email = models.EmailField(blank=True, default="", verbose_name="E-Mail")
    phone = models.CharField(
        max_length=40, blank=True, default="", verbose_name="Telefon"
    )
    birth_date = models.DateField(blank=True, null=True, verbose_name="Geburtsdatum")
    hired_on = models.DateField(verbose_name="Eintritt")
    left_on = models.DateField(blank=True, null=True, verbose_name="Austritt")
    work_time_model = fk(
        WorkTimeModel,
        related_name="employees",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="Arbeitszeitmodell",
    )
    qualifications = models.ManyToManyField(
        Qualification,
        through="EmployeeQualification",
        related_name="employees",
        blank=True,
    )
    notes = models.TextField(blank=True, default="", verbose_name="Notizen")

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name = "Mitarbeitende"
        verbose_name_plural = "Mitarbeitende"

    def __str__(self) -> str:
        return self.get_full_name()

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_active(self) -> bool:
        return self.left_on is None

    @property
    def may_administer(self) -> bool:
        """Darf Stammdaten, Personal und Dienstplanung verwalten."""
        return self.access_level == "admin"

    @property
    def may_write(self) -> bool:
        """Darf in den eigenen Gruppen schreiben."""
        return self.access_level in ("admin", "specialist")

    @property
    def is_specialist(self) -> bool:
        """Traegt die Person eine Fachkraftqualifikation?"""
        return self.qualifications.filter(is_specialist=True).exists()


class EmployeeQualification(models.Model):
    """Zuordnung einer Qualifikation mit Gueltigkeit."""

    employee = fk(Employee, related_name="employee_qualifications")
    qualification = fk(Qualification, related_name="employee_qualifications")
    acquired_on = models.DateField(blank=True, null=True, verbose_name="Erworben am")
    expires_on = models.DateField(
        blank=True,
        null=True,
        verbose_name="Gültig bis",
        help_text="Für Nachweise, die aufgefrischt werden müssen",
    )

    class Meta:
        unique_together = ("employee", "qualification")
        ordering = ["qualification__name"]
        verbose_name = "Qualifikationsnachweis"
        verbose_name_plural = "Qualifikationsnachweise"

    def __str__(self) -> str:
        return f"{self.employee} – {self.qualification}"


class Contract(models.Model):
    """Vertragsdaten. Mehrere Vertraege je Person bilden die Historie."""

    KIND_CHOICES = [
        ("permanent", "Unbefristet"),
        ("temporary", "Befristet"),
        ("minijob", "Geringfügig"),
        ("freelance", "Honorarkraft"),
        ("trainee", "Ausbildung / Praktikum"),
    ]

    employee = fk(Employee, related_name="contracts", verbose_name="Mitarbeitende")
    kind = models.CharField(
        max_length=20,
        choices=KIND_CHOICES,
        default="permanent",
        verbose_name="Vertragsart",
    )
    weekly_hours = models.DecimalField(
        max_digits=5, decimal_places=2, verbose_name="Wochenstunden"
    )
    pay_grade = models.CharField(
        max_length=40,
        blank=True,
        default="",
        verbose_name="Entgeltgruppe",
        help_text="z. B. TVöD SuE S 11b, Stufe 3",
    )
    valid_from = models.DateField(verbose_name="Gültig ab")
    valid_to = models.DateField(blank=True, null=True, verbose_name="Gültig bis")
    notes = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-valid_from"]
        verbose_name = "Vertrag"
        verbose_name_plural = "Verträge"

    def __str__(self) -> str:
        return f"{self.employee} – {self.get_kind_display()} ab {self.valid_from}"

    @property
    def fte(self) -> Decimal:
        """Vollzeitaequivalent, gemessen am Arbeitszeitmodell der Person."""
        model = self.employee.work_time_model
        if not model or not model.weekly_hours:
            return Decimal("0")
        return (self.weekly_hours / model.weekly_hours).quantize(Decimal("0.01"))


class Position(models.Model):
    """
    Stelle im Stellplan.

    Der Soll-Umfang steht hier, die tatsaechliche Besetzung in
    PositionAssignment. Aus der Differenz ergibt sich, ob eine Stelle frei,
    besetzt oder ueberbesetzt ist.
    """

    department = fk(Department, related_name="positions", verbose_name="Bereich")
    title = models.CharField(max_length=120, verbose_name="Stellenbezeichnung")
    target_fte = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("1.00"),
        verbose_name="Soll-Stellenanteil",
    )
    requires_specialist = models.BooleanField(
        default=True, verbose_name="Fachkraftstelle"
    )
    notes = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["department", "title"]
        verbose_name = "Stelle"
        verbose_name_plural = "Stellen"

    def __str__(self) -> str:
        return f"{self.title} ({self.department})"

    @property
    def assigned_fte(self) -> Decimal:
        total = sum(
            (assignment.fte for assignment in self.assignments.all()), Decimal("0")
        )
        return Decimal(total).quantize(Decimal("0.01"))

    @property
    def state(self) -> str:
        assigned = self.assigned_fte
        if assigned == 0:
            return "vacant"
        if assigned < self.target_fte:
            return "understaffed"
        if assigned > self.target_fte:
            return "overstaffed"
        return "filled"


class PositionAssignment(models.Model):
    """Besetzung einer Stelle durch eine Person, ganz oder anteilig."""

    position = fk(Position, related_name="assignments", verbose_name="Stelle")
    employee = fk(Employee, related_name="assignments", verbose_name="Mitarbeitende")
    fte = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("1.00"),
        verbose_name="Stellenanteil",
    )
    valid_from = models.DateField(verbose_name="Ab")
    valid_to = models.DateField(blank=True, null=True, verbose_name="Bis")

    class Meta:
        ordering = ["-valid_from"]
        verbose_name = "Stellenbesetzung"
        verbose_name_plural = "Stellenbesetzungen"

    def __str__(self) -> str:
        return f"{self.employee} auf {self.position} ({self.fte})"


@receiver(post_save, sender=Employee)
def sync_staff_flag(sender, instance, **kwargs):
    """
    Haelt Djangos is_staff an der Zugriffsstufe fest.

    Die Anwendung entscheidet ueber access_level, der Django-Admin ueber
    is_staff. Liefen die beiden auseinander, koennte jemand im Admin
    schalten, was ihm in der Anwendung verwehrt ist - oder umgekehrt sich
    selbst aussperren, ohne zu verstehen warum.
    """
    if instance.user_id is None:
        return

    wanted = instance.access_level == "admin"
    user = instance.user
    if user is None or user.is_staff == wanted:
        return

    # Superuser bleiben unangetastet: ihnen das Flag zu nehmen waere der
    # kuerzeste Weg, sich aus dem eigenen System auszusperren.
    if user.is_superuser and not wanted:
        return

    user.is_staff = wanted
    user.save(update_fields=["is_staff"])


# Änderungsprotokoll und die zugehörigen Signale werden hier eingehängt,
# damit Django beides beim Laden der App registriert.
from .audit import AuditEvent  # noqa: E402,F401  (am Ende, wegen Zyklen)
