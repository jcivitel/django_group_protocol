"""
Dienstplanung, Abwesenheiten und Zeiterfassung.

Deckt die Phasen 2 bis 4 der Roadmap ab. Grundlage sind die Stammdaten aus
django_grp_org: Bereiche, Mitarbeitende, Qualifikationen und
Arbeitszeitmodelle.

Zu db_constraint=False siehe django_grp_org.models.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from django_grp_org.models import Department, Employee, Provider, fk

# ============================================================ Phase 2


class ShiftType(models.Model):
    """
    Dienstart - Fruehdienst, Spaetdienst, Nachtbereitschaft und so weiter.

    Die Zeiten stehen hier einmal, damit ein Dienst im Plan nur noch Datum,
    Art und Person braucht.
    """

    provider = fk(Provider, related_name="shift_types", verbose_name="Träger")
    name = models.CharField(max_length=80, verbose_name="Bezeichnung")
    short_code = models.CharField(
        max_length=6, verbose_name="Kürzel", help_text="Erscheint im Dienstplanraster"
    )
    start_time = models.TimeField(verbose_name="Beginn")
    end_time = models.TimeField(verbose_name="Ende")
    break_minutes = models.PositiveIntegerField(
        default=30, verbose_name="Pause in Minuten"
    )
    color = models.CharField(max_length=9, default="#abc270", verbose_name="Farbe")
    is_night = models.BooleanField(
        default=False,
        verbose_name="Nachtdienst",
        help_text="Zählt für Nachtzuschläge und Ruhezeitprüfung",
    )
    is_on_call = models.BooleanField(
        default=False,
        verbose_name="Bereitschaft",
        help_text="Wird als Bereitschaftszeit gebucht, nicht als volle Arbeitszeit",
    )
    counts_specialist = models.BooleanField(
        default=True,
        verbose_name="Zählt für Fachkraftquote",
    )

    class Meta:
        ordering = ["provider", "start_time"]
        verbose_name = "Dienstart"
        verbose_name_plural = "Dienstarten"

    def __str__(self) -> str:
        return f"{self.short_code} · {self.name}"

    @property
    def duration_hours(self) -> Decimal:
        """Netto-Dauer in Stunden. Dienste über Mitternacht werden mitgezählt."""
        base = datetime(2000, 1, 1)
        start = base.replace(hour=self.start_time.hour, minute=self.start_time.minute)
        end = base.replace(hour=self.end_time.hour, minute=self.end_time.minute)
        if end <= start:
            end += timedelta(days=1)
        minutes = (end - start).total_seconds() / 60 - self.break_minutes
        return (Decimal(minutes) / Decimal(60)).quantize(Decimal("0.01"))


class DutyPlan(models.Model):
    """Dienstplan eines Bereichs für einen Monat."""

    STATUS_CHOICES = [
        ("draft", "Entwurf"),
        ("published", "Veröffentlicht"),
        ("locked", "Abgeschlossen"),
    ]

    department = fk(Department, related_name="duty_plans", verbose_name="Bereich")
    year = models.PositiveIntegerField(verbose_name="Jahr")
    month = models.PositiveSmallIntegerField(verbose_name="Monat")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="draft", verbose_name="Status"
    )
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("department", "year", "month")
        ordering = ["-year", "-month"]
        verbose_name = "Dienstplan"
        verbose_name_plural = "Dienstpläne"

    def __str__(self) -> str:
        return f"{self.department} {self.month:02d}/{self.year}"

    @property
    def is_editable(self) -> bool:
        return self.status != "locked"


class Shift(models.Model):
    """
    Ein einzelner Dienst.

    Ohne `employee` ist der Dienst offen - genau das zeigt der Plan als Lücke
    und die Vertretungssuche als zu besetzen an.
    """

    plan = fk(DutyPlan, related_name="shifts", verbose_name="Dienstplan")
    date = models.DateField(verbose_name="Datum")
    shift_type = fk(ShiftType, related_name="shifts", verbose_name="Dienstart")
    employee = fk(
        Employee,
        related_name="shifts",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="Mitarbeitende",
    )
    is_substitute = models.BooleanField(
        default=False,
        verbose_name="Vertretung",
        help_text="Kurzfristig übernommen, etwa bei Krankheit",
    )
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["date", "shift_type__start_time"]
        verbose_name = "Dienst"
        verbose_name_plural = "Dienste"

    def __str__(self) -> str:
        who = self.employee.get_full_name() if self.employee else "offen"
        return f"{self.date} {self.shift_type.short_code} – {who}"

    @property
    def starts_at(self):
        return timezone.make_aware(
            datetime.combine(self.date, self.shift_type.start_time)
        )

    @property
    def ends_at(self):
        end = datetime.combine(self.date, self.shift_type.end_time)
        if self.shift_type.end_time <= self.shift_type.start_time:
            end += timedelta(days=1)
        return timezone.make_aware(end)


# ============================================================ Phase 3


class AbsenceType(models.Model):
    """Abwesenheitsart - Urlaub, Krankheit, Fortbildung und Ähnliches."""

    KIND_CHOICES = [
        ("vacation", "Urlaub"),
        ("sick", "Krankheit"),
        ("training", "Fortbildung"),
        ("special", "Sonderurlaub"),
        ("unpaid", "Unbezahlt"),
        ("other", "Sonstiges"),
    ]

    provider = fk(Provider, related_name="absence_types", verbose_name="Träger")
    name = models.CharField(max_length=80, verbose_name="Bezeichnung")
    kind = models.CharField(
        max_length=20, choices=KIND_CHOICES, default="vacation", verbose_name="Art"
    )
    reduces_vacation = models.BooleanField(
        default=True,
        verbose_name="Vom Urlaubskonto abziehen",
    )
    requires_approval = models.BooleanField(
        default=True,
        verbose_name="Genehmigungspflichtig",
        help_text="Krankmeldungen brauchen meist keine Genehmigung",
    )
    color = models.CharField(max_length=9, default="#fda769", verbose_name="Farbe")

    class Meta:
        ordering = ["provider", "name"]
        verbose_name = "Abwesenheitsart"
        verbose_name_plural = "Abwesenheitsarten"

    def __str__(self) -> str:
        return self.name


class Absence(models.Model):
    """
    Abwesenheit einer Person über einen Zeitraum.

    Genehmigte Abwesenheiten machen betroffene Dienste zu offenen Diensten -
    das erledigt ein Signal, damit der Plan nicht stillschweigend falsch
    bleibt.
    """

    STATUS_CHOICES = [
        ("requested", "Beantragt"),
        ("approved", "Genehmigt"),
        ("rejected", "Abgelehnt"),
        ("cancelled", "Zurückgezogen"),
    ]

    employee = fk(Employee, related_name="absences", verbose_name="Mitarbeitende")
    absence_type = fk(AbsenceType, related_name="absences", verbose_name="Art")
    start_date = models.DateField(verbose_name="Von")
    end_date = models.DateField(verbose_name="Bis")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="requested",
        verbose_name="Status",
    )
    note = models.CharField(
        max_length=200, blank=True, default="", verbose_name="Anmerkung"
    )
    decided_by = fk(
        Employee,
        related_name="decided_absences",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="Entschieden von",
    )
    decided_at = models.DateTimeField(blank=True, null=True)
    decision_note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name = "Abwesenheit"
        verbose_name_plural = "Abwesenheiten"

    def __str__(self) -> str:
        return f"{self.employee} {self.absence_type} {self.start_date}–{self.end_date}"

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    def covers(self, day) -> bool:
        return self.start_date <= day <= self.end_date


# ============================================================ Phase 4


class TimeEntry(models.Model):
    """
    Zeitbuchung. Entsteht entweder aus einem Dienst oder von Hand.

    `shift` bleibt leer, wenn jemand ausserhalb des Plans gearbeitet hat -
    etwa bei einer Fortbildung oder einem Elterngespräch am freien Tag.
    """

    CATEGORY_CHOICES = [
        ("work", "Arbeitszeit"),
        ("on_call", "Bereitschaft"),
        ("training", "Fortbildung"),
        ("travel", "Reisezeit"),
    ]

    employee = fk(Employee, related_name="time_entries", verbose_name="Mitarbeitende")
    shift = fk(
        Shift,
        related_name="time_entries",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="Dienst",
    )
    date = models.DateField(verbose_name="Datum")
    start_time = models.TimeField(verbose_name="Beginn")
    end_time = models.TimeField(verbose_name="Ende")
    break_minutes = models.PositiveIntegerField(
        default=0, verbose_name="Pause in Minuten"
    )
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default="work", verbose_name="Art"
    )
    note = models.CharField(max_length=200, blank=True, default="")
    approved = models.BooleanField(default=False, verbose_name="Freigegeben")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "start_time"]
        verbose_name = "Zeitbuchung"
        verbose_name_plural = "Zeitbuchungen"

    def __str__(self) -> str:
        return f"{self.employee} {self.date} {self.start_time}–{self.end_time}"

    @property
    def hours(self) -> Decimal:
        base = datetime(2000, 1, 1)
        start = base.replace(hour=self.start_time.hour, minute=self.start_time.minute)
        end = base.replace(hour=self.end_time.hour, minute=self.end_time.minute)
        if end <= start:
            end += timedelta(days=1)
        minutes = (end - start).total_seconds() / 60 - self.break_minutes
        return (Decimal(max(minutes, 0)) / Decimal(60)).quantize(Decimal("0.01"))

    @property
    def credited_hours(self) -> Decimal:
        """Bereitschaft zählt nur anteilig auf das Arbeitszeitkonto."""
        if self.category == "on_call":
            return (self.hours * Decimal("0.5")).quantize(Decimal("0.01"))
        return self.hours


class TimeAccount(models.Model):
    """
    Monatliches Zeitkonto.

    Wird beim Monatsabschluss aus den Buchungen gefüllt. Der Übertrag hält
    Mehr- und Minderstunden über die Monate hinweg nach.
    """

    employee = fk(Employee, related_name="time_accounts", verbose_name="Mitarbeitende")
    year = models.PositiveIntegerField(verbose_name="Jahr")
    month = models.PositiveSmallIntegerField(verbose_name="Monat")
    target_hours = models.DecimalField(
        max_digits=7, decimal_places=2, default=Decimal("0"), verbose_name="Soll"
    )
    actual_hours = models.DecimalField(
        max_digits=7, decimal_places=2, default=Decimal("0"), verbose_name="Ist"
    )
    carry_over = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name="Übertrag aus Vormonat",
    )
    on_call_hours = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name="Bereitschaft",
    )
    night_hours = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name="Nachtstunden",
    )
    closed_at = models.DateTimeField(
        blank=True, null=True, verbose_name="Abgeschlossen am"
    )

    class Meta:
        unique_together = ("employee", "year", "month")
        ordering = ["-year", "-month"]
        verbose_name = "Zeitkonto"
        verbose_name_plural = "Zeitkonten"

    def __str__(self) -> str:
        return f"{self.employee} {self.month:02d}/{self.year}"

    @property
    def balance(self) -> Decimal:
        """Saldo des Monats einschließlich Übertrag."""
        return (self.actual_hours - self.target_hours + self.carry_over).quantize(
            Decimal("0.01")
        )


# ============================================================ Signale


@receiver(post_save, sender=Absence)
def release_shifts_when_approved(sender, instance, **kwargs):
    """
    Genehmigte Abwesenheiten geben die betroffenen Dienste frei.

    Der Dienst bleibt bestehen und wird nur unbesetzt - so bleibt der Bedarf
    im Plan sichtbar, statt stillschweigend zu verschwinden.
    """
    if instance.status != "approved":
        return
    from .services import release_shifts_for_absence

    release_shifts_for_absence(instance)


# ============================================================ Phase 7


class ShiftPreference(models.Model):
    """
    Wunsch oder Sperre für einen Tag.

    Die Planung sieht beim Besetzen, wer sich einen Tag wünscht und wer ihn
    nicht kann. Verbindlich ist das nicht - es ist eine Angabe, keine
    Zusage, und genau so steht es auch in der Oberfläche.
    """

    KIND_CHOICES = [
        ("wish", "Wunsch"),
        ("block", "Möchte nicht"),
        ("unavailable", "Nicht verfügbar"),
    ]

    employee = fk(Employee, related_name="preferences", verbose_name="Mitarbeitende")
    date = models.DateField(verbose_name="Datum")
    shift_type = fk(
        ShiftType,
        related_name="preferences",
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        verbose_name="Dienstart",
        help_text="Leer lassen, wenn der ganze Tag gemeint ist",
    )
    kind = models.CharField(
        max_length=20, choices=KIND_CHOICES, default="wish", verbose_name="Art"
    )
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("employee", "date", "shift_type")
        ordering = ["date"]
        verbose_name = "Dienstwunsch"
        verbose_name_plural = "Dienstwünsche"

    def __str__(self) -> str:
        what = self.shift_type.short_code if self.shift_type_id else "ganzer Tag"
        return f"{self.employee} {self.date} {what}: {self.get_kind_display()}"


class ShiftSwap(models.Model):
    """
    Diensttausch.

    Ablauf: jemand bietet einen Dienst an, eine zweite Person nimmt ihn an,
    die Leitung bestätigt. Erst mit der Bestätigung wechselt der Dienst die
    Person - vorher ist nichts entschieden, und der Plan bleibt gültig.
    """

    STATUS_CHOICES = [
        ("offered", "Angeboten"),
        ("accepted", "Angenommen"),
        ("confirmed", "Bestätigt"),
        ("declined", "Abgelehnt"),
        ("withdrawn", "Zurückgezogen"),
    ]

    shift = fk(Shift, related_name="swaps", verbose_name="Dienst")
    offered_by = fk(Employee, related_name="offered_swaps", verbose_name="Bietet an")
    accepted_by = fk(
        Employee,
        related_name="accepted_swaps",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="Übernimmt",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="offered", verbose_name="Status"
    )
    reason = models.CharField(
        max_length=200, blank=True, default="", verbose_name="Grund"
    )
    decided_by = fk(
        Employee,
        related_name="decided_swaps",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="Bestätigt von",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Diensttausch"
        verbose_name_plural = "Diensttausche"

    def __str__(self) -> str:
        return f"{self.shift} – {self.get_status_display()}"

    @property
    def is_open(self) -> bool:
        return self.status in ("offered", "accepted")


@receiver(post_save, sender=ShiftSwap)
def apply_confirmed_swap(sender, instance, **kwargs):
    """Mit der Bestätigung wechselt der Dienst die Person."""
    if instance.status != "confirmed" or not instance.accepted_by_id:
        return

    shift = instance.shift
    if shift.employee_id == instance.accepted_by_id:
        return

    shift.employee_id = instance.accepted_by_id
    shift.is_substitute = True
    note = f"Getauscht von {instance.offered_by.get_full_name()}"
    shift.note = note if not shift.note else f"{shift.note} · {note}"
    shift.save(update_fields=["employee", "is_substitute", "note"])
