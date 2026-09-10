"""
Die Bewohnerakte jenseits der Stammdaten (Roadmap Phase 10).

Allergien und Einwilligungen stehen in `models.py` neben `Resident`, weil sie
zuerst kamen. Alles Weitere steht hier: An- und Abwesenheit, Medikation mit
Nachweis, besondere Vorkommnisse, Checklisten, Barbetrag.

Der Zuschnitt folgt `bewohnerakte_konzept.md` im Wurzelverzeichnis. Drei
Regeln daraus stehen im Modell und nicht bloß im Kopf:

1. **Eine Gabe ist unveränderlich.** Wie ein exportiertes Protokoll. Wer sich
   vertippt, trägt eine Korrektur nach; die alte Zeile bleibt stehen. Ein
   Nachweis, der sich ändern lässt, ist keiner.
2. **Eine ausgelassene Gabe ist auch eine Gabe.** Das Feld `skipped` mit
   `reason` ist wichtiger als das Häkchen daneben — es beantwortet die Frage,
   die später gestellt wird.
3. **Belegungstage sind Geld.** Die An- und Abwesenheit des Kindes trägt die
   Abrechnung mit dem Jugendamt, nicht nur die Frage, wo jemand heute Nacht
   ist.
"""

from datetime import date

from django.contrib.auth.models import User
from django.db import models

from .models import Resident


def fk(to, **kwargs):
    """Fremdschlüssel mit CASCADE — alles hier hängt an einer Person."""
    kwargs.setdefault("on_delete", models.CASCADE)
    return models.ForeignKey(to, **kwargs)


class ResidentAbsence(models.Model):
    """
    Wann ein Kind nicht da war.

    Zwei Fragen auf einmal. Fachlich: ist das Kind heute Nacht im Haus?
    Wirtschaftlich: wie viele Belegungstage rechnet der Monat? Beide hängen
    an denselben Zeilen, deshalb gibt es nur eine Tabelle.

    **Unerlaubte Abwesenheit ist eine eigene Art und keine Anmerkung.** Sie
    zieht in aller Regel eine Meldung nach § 47 SGB VIII nach sich, und wer
    sie im Freitext versteckt, findet sie im Ernstfall nicht wieder.
    """

    KIND_CHOICES = [
        ("home", "Heimfahrt"),
        ("holiday", "Ferien"),
        ("clinic", "Klinik"),
        ("unauthorised", "Unerlaubt abwesend"),
        ("other", "Sonstiges"),
    ]

    resident = fk(Resident, related_name="absences", verbose_name="Bewohner:in")
    kind = models.CharField(
        max_length=20, choices=KIND_CHOICES, verbose_name="Art"
    )
    start_date = models.DateField(verbose_name="Von")
    end_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="Bis",
        help_text="Leer, solange die Abwesenheit läuft",
    )
    counts_as_occupied = models.BooleanField(
        default=True,
        verbose_name="Zählt als belegt",
        help_text=(
            "Heimfahrt und Ferien zählen üblicherweise weiter als belegt, eine "
            "Klinikunterbringung ab einer gewissen Dauer nicht. Prüfen Sie das "
            "gegen die Entgeltvereinbarung."
        ),
    )
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name = "Abwesenheit"
        verbose_name_plural = "Abwesenheiten"

    def __str__(self) -> str:
        return f"{self.resident.get_full_name()}: {self.get_kind_display()}"

    @property
    def is_running(self) -> bool:
        heute = date.today()
        return self.start_date <= heute and (not self.end_date or self.end_date >= heute)


class Medication(models.Model):
    """
    Ein Medikament im Plan.

    `times` hält die Uhrzeiten als Liste, etwa `["08:00", "20:00"]`. Ein
    eigenes Modell je Zeitpunkt wäre sauberer und würde für drei Uhrzeiten
    drei Tabellenzeilen und einen Verbund brauchen — der Plan wird als Ganzes
    gelesen und als Ganzes geändert.

    Bedarfsmedikation hat keine Uhrzeiten. Sie steht trotzdem im Plan, damit
    im Dienst jemand weiß, dass es sie gibt.
    """

    resident = fk(Resident, related_name="medications", verbose_name="Bewohner:in")
    agent = models.CharField(
        max_length=120,
        verbose_name="Wirkstoff",
        help_text="Wonach im Zweifel gesucht wird",
    )
    product = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="Präparat",
        help_text="Handelsname, wie er auf der Packung steht",
    )
    dose = models.CharField(
        max_length=80, verbose_name="Dosis", help_text="z. B. 10 mg oder 1 Tablette"
    )
    times = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Zeitpunkte",
        help_text='Uhrzeiten als Liste, z. B. ["08:00", "20:00"]',
    )
    as_needed = models.BooleanField(
        default=False,
        verbose_name="Bedarfsmedikation",
        help_text="Ohne festen Zeitpunkt. Dann gehört die Bedingung in den Hinweis.",
    )
    prescribed_by = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="Verordnet von",
        help_text="Praxis oder Ärztin",
    )
    valid_from = models.DateField(verbose_name="Ab")
    valid_to = models.DateField(
        blank=True,
        null=True,
        verbose_name="Bis",
        help_text="Leer, solange es weiter gegeben wird",
    )
    note = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="Hinweis",
        help_text="Bedingung, Höchstmenge, was zu beachten ist",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["as_needed", "agent"]
        verbose_name = "Medikament"
        verbose_name_plural = "Medikamente"

    def __str__(self) -> str:
        return f"{self.resident.get_full_name()}: {self.agent} {self.dose}"

    @property
    def is_current(self) -> bool:
        heute = date.today()
        return self.valid_from <= heute and (not self.valid_to or self.valid_to >= heute)


class MedicationAdministration(models.Model):
    """
    Eine Gabe — oder eine ausdrücklich ausgelassene.

    **Unveränderlich.** Es gibt kein Bearbeiten und kein Löschen über die
    Anwendung, so wie es bei einem exportierten Protokoll keines gibt. Wer
    sich vertippt, trägt eine Korrektur nach; `corrects` zeigt auf die Zeile,
    die gemeint war. Beide bleiben stehen.

    Der Nachweis entsteht aus dem angemeldeten Konto. Eine zweite
    Bestätigung wäre sicherer und im Nachtdienst oft nicht zu leisten — dann
    bliebe der Nachweis liegen, und ein nachgetragener Nachweis ist keiner.
    """

    medication = fk(
        Medication, related_name="administrations", verbose_name="Medikament"
    )
    scheduled_for = models.DateTimeField(
        verbose_name="Vorgesehen",
        help_text="Der Zeitpunkt aus dem Plan; bei Bedarfsmedikation die Gabe selbst",
    )
    given_at = models.DateTimeField(
        blank=True, null=True, verbose_name="Gegeben um"
    )
    given_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="medication_administrations",
        verbose_name="Gegeben von",
    )
    given_by_name = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="Name",
        help_text=(
            "Der Name zum Zeitpunkt der Gabe. Er steht hier fest, damit der "
            "Nachweis lesbar bleibt, wenn das Konto später gelöscht wird."
        ),
    )
    amount = models.CharField(
        max_length=80, blank=True, default="", verbose_name="Menge"
    )
    skipped = models.BooleanField(
        default=False,
        verbose_name="Ausgelassen",
        help_text="Eine ausgelassene Gabe ist auch eine Gabe",
    )
    reason = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="Grund",
        help_text="Bei ausgelassener Gabe erforderlich",
    )
    corrects = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="corrections",
        verbose_name="Korrigiert",
        help_text="Zeigt auf die Zeile, die gemeint war",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-scheduled_for"]
        verbose_name = "Gabe"
        verbose_name_plural = "Gaben"

    def __str__(self) -> str:
        stand = "ausgelassen" if self.skipped else "gegeben"
        return f"{self.medication.agent} {stand} {self.scheduled_for:%d.%m. %H:%M}"

    def save(self, *args, **kwargs):
        """
        Einmal geschrieben, nicht mehr geaendert.

        Die Sperre steht im Modell und nicht nur in der Schnittstelle: sie
        soll auch fuer die Django-Verwaltung und fuer ein Skript gelten. Wer
        eine Gabe berichtigen muss, legt eine neue Zeile mit `corrects` an -
        dann stehen beide da, und das ist der Sinn eines Nachweises.
        """
        if self.pk is not None:
            raise ValueError(
                "Eine Gabe laesst sich nicht aendern. Fuer eine Berichtigung "
                "eine neue Zeile mit `corrects` anlegen."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Eine Gabe laesst sich nicht loeschen.")


class Incident(models.Model):
    """
    Ein besonderes Vorkommnis nach § 47 SGB VIII.

    Der Träger hat Ereignisse, die das Wohl der Kinder beeinträchtigen
    könnten, unverzüglich der Aufsichtsbehörde zu melden. Wer eine solche
    Meldung nicht belegen kann, hat sie im Zweifel nicht gemacht.

    Ein Eintrag im Gruppenprotokoll reicht dafür nicht: es braucht Zeitpunkt,
    Hergang, Sofortmaßnahme, Beteiligte und die Meldekette mit Datum.

    `resident` darf leer bleiben. Nicht jedes Vorkommnis lässt sich einer
    Person zuordnen — ein Brand in der Gruppe betrifft alle.
    """

    KIND_CHOICES = [
        ("absence", "Unerlaubte Abwesenheit"),
        ("violence", "Gewalt"),
        ("self_harm", "Selbstgefährdung"),
        ("accident", "Unfall"),
        ("police", "Polizeieinsatz"),
        ("suspicion", "Verdacht nach § 8a"),
        ("substance", "Suchtmittel"),
        ("other", "Sonstiges"),
    ]

    STATUS_CHOICES = [
        ("open", "Offen"),
        ("reported", "Gemeldet"),
        ("closed", "Abgeschlossen"),
    ]

    group = fk(
        "django_grp_backend.Group",
        related_name="incidents",
        verbose_name="Gruppe",
    )
    resident = models.ForeignKey(
        Resident,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="incidents",
        verbose_name="Bewohner:in",
        help_text="Leer lassen, wenn es die Gruppe insgesamt betrifft",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, verbose_name="Art")
    occurred_at = models.DateTimeField(verbose_name="Zeitpunkt")
    description = models.TextField(
        verbose_name="Hergang", help_text="Was geschehen ist, sachlich"
    )
    immediate_action = models.TextField(
        blank=True,
        default="",
        verbose_name="Sofortmaßnahme",
        help_text="Was unmittelbar getan wurde",
    )
    participants = models.CharField(
        max_length=300,
        blank=True,
        default="",
        verbose_name="Beteiligte",
        help_text="Wer dabei war, wer verständigt wurde",
    )
    reported_to = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="Gemeldet an",
        help_text="Landesjugendamt, Jugendamt, Polizei",
    )
    reported_at = models.DateTimeField(
        blank=True, null=True, verbose_name="Gemeldet am"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="open",
        verbose_name="Stand",
    )
    recorded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="incidents",
        verbose_name="Aufgenommen von",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name = "Besonderes Vorkommnis"
        verbose_name_plural = "Besondere Vorkommnisse"

    def __str__(self) -> str:
        return f"{self.get_kind_display()} am {self.occurred_at:%d.%m.%Y}"

    @property
    def needs_report(self) -> bool:
        """Offen und noch nicht gemeldet — die Zeile, die oben stehen muss."""
        return self.status == "open" and self.reported_at is None


class ChecklistItem(models.Model):
    """
    Ein Punkt der Aufnahme- oder Entlassungscheckliste.

    Bei einer Aufnahme fällt vieles gleichzeitig an, und manches fällt hinten
    runter. Eine Liste, die man abhaken kann, ist hier kein Bürokratismus,
    sondern das Gegenteil: sie macht sichtbar, was noch offen ist.
    """

    KIND_CHOICES = [
        ("admission", "Aufnahme"),
        ("discharge", "Entlassung"),
    ]

    resident = fk(
        Resident, related_name="checklist_items", verbose_name="Bewohner:in"
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, verbose_name="Art")
    title = models.CharField(max_length=150, verbose_name="Was")
    done_on = models.DateField(blank=True, null=True, verbose_name="Erledigt am")
    done_by = models.CharField(
        max_length=120, blank=True, default="", verbose_name="Erledigt von"
    )
    note = models.CharField(max_length=200, blank=True, default="")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["kind", "position", "id"]
        verbose_name = "Checklistenpunkt"
        verbose_name_plural = "Checklistenpunkte"

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.title}"


class PocketMoneyEntry(models.Model):
    """
    Eine Buchung auf dem Barbetrag nach § 39 SGB VIII.

    Der Barbetrag steht dem Kind zu und ist nachzuweisen. Heute läuft er in
    vielen Häusern über ein Heft; ein Heft beantwortet die Frage „wie viel
    hat das Kind noch" erst nach dem Zusammenzählen.

    Kein eigenes Kontomodell: der Stand ist die Summe der Buchungen. Ein
    gespeicherter Saldo müsste gepflegt werden und wäre nach der ersten
    nachgetragenen Zeile falsch.
    """

    KIND_CHOICES = [
        ("credit", "Gutschrift"),
        ("payout", "Auszahlung"),
        ("correction", "Korrektur"),
    ]

    resident = fk(
        Resident, related_name="pocket_money", verbose_name="Bewohner:in"
    )
    date = models.DateField(verbose_name="Datum")
    kind = models.CharField(
        max_length=20,
        choices=KIND_CHOICES,
        default="payout",
        verbose_name="Art",
    )
    amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        verbose_name="Betrag",
        help_text="Gutschrift positiv, Auszahlung positiv — die Art entscheidet das Vorzeichen",
    )
    note = models.CharField(max_length=200, blank=True, default="")
    recorded_by = models.CharField(
        max_length=120, blank=True, default="", verbose_name="Erfasst von"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "Barbetrag-Buchung"
        verbose_name_plural = "Barbetrag-Buchungen"

    def __str__(self) -> str:
        return f"{self.resident.get_full_name()}: {self.get_kind_display()} {self.amount}"

    @property
    def signed_amount(self):
        """Was die Buchung zum Stand beiträgt."""
        return self.amount if self.kind == "credit" else -self.amount
