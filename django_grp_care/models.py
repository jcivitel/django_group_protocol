"""
Hilfeplanung und Fallführung nach SGB VIII.

Phase 5 der Roadmap. Eine Fallakte gehört zu einem Bewohner; darin liegen
fortgeschriebene Hilfepläne mit Zielen und Maßnahmen, die Beteiligten und
die Protokolle der Hilfeplangespräche.

Die Verbindung zu den Gruppenprotokollen läuft über
ProtocolObservation.resident: Verlaufseinträge zu einer Person erscheinen in
deren Fallakte, ohne dass Protokolle doppelt abgelegt werden.

Zu db_constraint=False siehe django_grp_org.models.
"""

from django.db import models

from django_grp_org.models import Employee, Provider, fk


class CaseFile(models.Model):
    """Fallakte einer betreuten Person."""

    STATUS_CHOICES = [
        ("open", "Laufend"),
        ("paused", "Ruhend"),
        ("closed", "Abgeschlossen"),
    ]

    provider = fk(Provider, related_name="case_files", verbose_name="Träger")
    resident = fk(
        "django_grp_backend.Resident",
        related_name="case_files",
        verbose_name="Bewohner",
    )
    case_number = models.CharField(
        max_length=40, blank=True, default="", verbose_name="Aktenzeichen"
    )
    youth_office = models.CharField(
        max_length=150, blank=True, default="", verbose_name="Zuständiges Jugendamt"
    )
    case_manager = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="Fallführung Jugendamt",
        help_text="Name der zuständigen Person im Jugendamt",
    )
    responsible = fk(
        Employee,
        related_name="case_files",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="Bezugsbetreuung",
    )
    opened_on = models.DateField(verbose_name="Aufnahme")
    closed_on = models.DateField(blank=True, null=True, verbose_name="Abschluss")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="open", verbose_name="Status"
    )
    note = models.TextField(blank=True, default="", verbose_name="Notizen")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-opened_on"]
        verbose_name = "Fallakte"
        verbose_name_plural = "Fallakten"

    def __str__(self) -> str:
        return f"Fallakte {self.resident}"

    @property
    def current_plan(self):
        """Der aktuell gültige Hilfeplan, sofern es einen gibt."""
        return self.help_plans.filter(status="active").order_by("-version").first()


class CaseParticipant(models.Model):
    """
    Beteiligte am Fall.

    Jugendamt, Sorgeberechtigte, Vormund, Schule, Therapie - alle, die im
    Hilfeplanverfahren mitreden oder informiert werden müssen.
    """

    KIND_CHOICES = [
        ("youth_office", "Jugendamt"),
        ("guardian", "Sorgeberechtigt"),
        ("custodian", "Vormund"),
        ("parent", "Elternteil"),
        ("child", "Kind / Jugendliche:r"),
        ("school", "Schule"),
        ("therapy", "Therapie / Medizin"),
        ("facility", "Einrichtung"),
        ("other", "Sonstige"),
    ]

    case_file = fk(CaseFile, related_name="participants", verbose_name="Fallakte")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, verbose_name="Rolle")
    name = models.CharField(max_length=120, verbose_name="Name")
    organisation = models.CharField(
        max_length=120, blank=True, default="", verbose_name="Organisation"
    )
    contact = models.CharField(
        max_length=150,
        blank=True,
        default="",
        verbose_name="Kontakt",
        help_text="Telefon oder E-Mail",
    )
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["kind", "name"]
        verbose_name = "Beteiligte:r"
        verbose_name_plural = "Beteiligte"

    def __str__(self) -> str:
        return f"{self.name} ({self.get_kind_display()})"


class HelpPlan(models.Model):
    """
    Hilfeplan nach § 36 SGB VIII.

    Fortschreibungen entstehen als neue Version mit Verweis auf die
    vorherige; die alte wird auf "superseded" gesetzt. So bleibt die
    Entwicklung nachvollziehbar, statt einen Datensatz zu überschreiben.
    """

    LEGAL_BASIS_CHOICES = [
        ("27", "§ 27 Hilfe zur Erziehung"),
        ("29", "§ 29 Soziale Gruppenarbeit"),
        ("30", "§ 30 Erziehungsbeistand"),
        ("31", "§ 31 Sozialpädagogische Familienhilfe"),
        ("32", "§ 32 Erziehung in einer Tagesgruppe"),
        ("33", "§ 33 Vollzeitpflege"),
        ("34", "§ 34 Heimerziehung"),
        ("35", "§ 35 Intensive sozialpädagogische Einzelbetreuung"),
        ("35a", "§ 35a Eingliederungshilfe"),
        ("41", "§ 41 Hilfe für junge Volljährige"),
    ]

    STATUS_CHOICES = [
        ("draft", "Entwurf"),
        ("active", "Gültig"),
        ("superseded", "Fortgeschrieben"),
        ("closed", "Beendet"),
    ]

    case_file = fk(CaseFile, related_name="help_plans", verbose_name="Fallakte")
    version = models.PositiveIntegerField(default=1, verbose_name="Fassung")
    previous = fk(
        "self",
        related_name="successors",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="Vorherige Fassung",
    )
    legal_basis = models.CharField(
        max_length=5, choices=LEGAL_BASIS_CHOICES, verbose_name="Rechtsgrundlage"
    )
    help_form = models.CharField(
        max_length=150,
        blank=True,
        default="",
        verbose_name="Hilfeform",
        help_text="z. B. Familienanaloge Wohngruppe, Tagesgruppe",
    )
    valid_from = models.DateField(verbose_name="Gültig ab")
    valid_to = models.DateField(blank=True, null=True, verbose_name="Gültig bis")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="draft", verbose_name="Status"
    )
    situation = models.TextField(blank=True, default="", verbose_name="Ausgangslage")
    review_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="Nächste Fortschreibung",
        help_text="Erscheint als Frist im Kalender",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-version"]
        verbose_name = "Hilfeplan"
        verbose_name_plural = "Hilfepläne"

    def __str__(self) -> str:
        return f"{self.case_file.resident} – Hilfeplan v{self.version}"

    @property
    def goal_progress(self) -> int:
        """Anteil erreichter Ziele in Prozent."""
        goals = list(self.goals.all())
        if not goals:
            return 0
        achieved = sum(1 for goal in goals if goal.status == "achieved")
        return round(achieved * 100 / len(goals))


class HelpGoal(models.Model):
    """Ziel im Hilfeplan."""

    CATEGORY_CHOICES = [
        ("education", "Erziehung und Entwicklung"),
        ("school", "Schule und Ausbildung"),
        ("health", "Gesundheit"),
        ("social", "Soziale Beziehungen"),
        ("family", "Familie und Herkunft"),
        ("independence", "Verselbständigung"),
        ("other", "Sonstiges"),
    ]

    STATUS_CHOICES = [
        ("open", "Offen"),
        ("in_progress", "In Arbeit"),
        ("achieved", "Erreicht"),
        ("dropped", "Nicht weiterverfolgt"),
    ]

    help_plan = fk(HelpPlan, related_name="goals", verbose_name="Hilfeplan")
    title = models.CharField(max_length=200, verbose_name="Ziel")
    description = models.TextField(blank=True, default="", verbose_name="Beschreibung")
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default="education",
        verbose_name="Bereich",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="open", verbose_name="Stand"
    )
    target_date = models.DateField(blank=True, null=True, verbose_name="Zieltermin")
    position = models.IntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "Hilfeplanziel"
        verbose_name_plural = "Hilfeplanziele"

    def __str__(self) -> str:
        return self.title


class HelpMeasure(models.Model):
    """Maßnahme, mit der ein Ziel verfolgt wird."""

    goal = fk(HelpGoal, related_name="measures", verbose_name="Ziel")
    title = models.CharField(max_length=200, verbose_name="Maßnahme")
    description = models.TextField(blank=True, default="", verbose_name="Beschreibung")
    responsible = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="Zuständig",
        help_text="Person, Dienst oder Stelle",
    )
    frequency = models.CharField(
        max_length=80,
        blank=True,
        default="",
        verbose_name="Rhythmus",
        help_text="z. B. wöchentlich, 14-tägig",
    )
    is_done = models.BooleanField(default=False, verbose_name="Abgeschlossen")
    position = models.IntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "Maßnahme"
        verbose_name_plural = "Maßnahmen"

    def __str__(self) -> str:
        return self.title


class CaseMeeting(models.Model):
    """
    Hilfeplangespräch oder Fallkonferenz.

    Beschlüsse stehen getrennt vom Protokolltext, weil sie später einzeln
    nachgehalten werden müssen.
    """

    KIND_CHOICES = [
        ("help_plan", "Hilfeplangespräch"),
        ("case_conference", "Fallkonferenz"),
        ("handover", "Übergabegespräch"),
        ("other", "Sonstiges"),
    ]

    case_file = fk(CaseFile, related_name="meetings", verbose_name="Fallakte")
    help_plan = fk(
        HelpPlan,
        related_name="meetings",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="Hilfeplan",
    )
    kind = models.CharField(
        max_length=20, choices=KIND_CHOICES, default="help_plan", verbose_name="Art"
    )
    date = models.DateField(verbose_name="Datum")
    location = models.CharField(
        max_length=150, blank=True, default="", verbose_name="Ort"
    )
    participants = models.TextField(blank=True, default="", verbose_name="Teilnehmende")
    minutes = models.TextField(blank=True, default="", verbose_name="Verlauf")
    decisions = models.TextField(blank=True, default="", verbose_name="Beschlüsse")
    next_meeting = models.DateField(
        blank=True, null=True, verbose_name="Nächster Termin"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "Fallgespräch"
        verbose_name_plural = "Fallgespräche"

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.date} – {self.case_file.resident}"
