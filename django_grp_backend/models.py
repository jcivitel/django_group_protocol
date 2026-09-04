import os
import random
import uuid

from PIL import Image
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.deconstruct import deconstructible

from django_grp_backend.access import is_admin
from django_grp_backend.functions import validate_image

# Hinweis zu db_constraint=False bei den Modellen ab ProtocolTemplate:
# Das Datenverzeichnis des Entwicklungs-Containers wird in
# utils/docker-compose.yml als Windows-Bind-Mount eingebunden
# (./mysql:/var/lib/mysql). InnoDB kann Dateien auf diesem Mount nicht
# umbenennen, wodurch jedes "ALTER TABLE ... ADD FOREIGN KEY" mit
# "Tablespace is missing" abbricht. Solange der Container so läuft, werden
# die neuen Beziehungen ohne Datenbank-Constraint angelegt; Django prüft sie
# weiterhin. Stellt der Container auf ein Docker-Volume um, kann
# db_constraint wieder entfallen.

# ============ CUSTOM QUERYSETS ============


class GroupQuerySet(models.QuerySet):
    """Custom QuerySet for Group model."""

    def for_user(self, user):
        """Gruppen, die das Konto sehen darf."""
        if is_admin(user):
            return self
        return self.filter(group_members=user)


class ResidentQuerySet(models.QuerySet):
    """Custom QuerySet for Resident model."""

    def for_user(self, user):
        """Bewohner der Gruppen, die das Konto sehen darf."""
        if is_admin(user):
            return self
        return self.filter(group__group_members=user)

    def active(self):
        """Return only active residents (not moved out)."""
        return self.filter(moved_out_since__isnull=True)


class ProtocolQuerySet(models.QuerySet):
    """Custom QuerySet for Protocol model."""

    def for_user(self, user):
        """Protokolle der Gruppen, die das Konto sehen darf."""
        if is_admin(user):
            return self
        return self.filter(group__group_members=user)

    def current_month(self):
        """Return protocols from current month."""
        from django.utils.timezone import now

        today = now().date()
        return self.filter(
            protocol_date__year=today.year, protocol_date__month=today.month
        )


# ============ CUSTOM MANAGERS ============


class GroupManager(models.Manager):
    """Custom manager for Group model."""

    def get_queryset(self):
        return GroupQuerySet(self.model, using=self._db)

    def for_user(self, user):
        return self.get_queryset().for_user(user)


class ResidentManager(models.Manager):
    """Custom manager for Resident model."""

    def get_queryset(self):
        return ResidentQuerySet(self.model, using=self._db)

    def for_user(self, user):
        return self.get_queryset().for_user(user)

    def active(self):
        return self.get_queryset().active()


class ProtocolManager(models.Manager):
    """Custom manager for Protocol model."""

    def get_queryset(self):
        return ProtocolQuerySet(self.model, using=self._db)

    def for_user(self, user):
        return self.get_queryset().for_user(user)

    def current_month(self):
        return self.get_queryset().current_month()


class Group(models.Model):
    name = models.CharField(max_length=100)
    short_name = models.CharField(
        max_length=8,
        blank=True,
        default="",
        verbose_name="Kürzel",
        help_text=(
            "Zwei bis vier Zeichen für Plaketten und enge Listen, etwa „6a“. "
            "Leer lassen: dann wird es aus dem Namen abgeleitet."
        ),
    )
    address = models.CharField(max_length=100)
    postalcode = models.CharField(max_length=10)
    city = models.CharField(max_length=100)
    color = models.CharField(max_length=9, default="#ffffff")
    group_members = models.ManyToManyField(User, blank=True)
    pdf_template = models.FileField(upload_to=f"docs/", blank=True, null=True)

    objects = GroupManager()

    def get_full_address(self):
        return f"{self.address},\n{self.postalcode}, {self.city}"

    @property
    def short_label(self) -> str:
        """
        Das Kürzel, immer gefüllt.

        Was hier steht, kommt in enge Listen: eine Plakette neben einem Namen
        hat Platz für zwei bis vier Zeichen. Ist keines gepflegt, wird eines
        abgeleitet - aber nur zur Anzeige, nicht in die Datenbank. Ein Feld,
        das sich beim Speichern selbst füllt, lässt sich hinterher nicht mehr
        von einer bewussten Eingabe unterscheiden.

        Die Ableitung nimmt das letzte Wort, wenn es kurz ist und eine Ziffer
        enthält - „Campuswohngruppe 6a" heißt im Haus schlicht „6a". Sonst
        die Anfangsbuchstaben der Wörter, sonst die ersten beiden Zeichen.
        """
        if self.short_name.strip():
            return self.short_name.strip()

        woerter = self.name.split()
        if not woerter:
            return "?"

        letztes = woerter[-1]
        if len(letztes) <= 4 and any(zeichen.isdigit() for zeichen in letztes):
            return letztes.upper()

        if len(woerter) > 1:
            return "".join(wort[0] for wort in woerter[:3]).upper()

        return self.name[:2].upper()

    def __str__(self):
        return self.name


@deconstructible
class RandomizedFileName:
    def __call__(self, instance, filename):
        ext = os.path.splitext(filename)[1]  # Get file extension
        random_name = uuid.uuid4().hex  # Generate random string
        return f"images/{random_name}{ext.lower()}"


class Resident(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    picture = models.ImageField(
        blank=True,
        null=True,
        upload_to=RandomizedFileName(),
        validators=[validate_image],
    )
    moved_in_since = models.DateField()
    moved_out_since = models.DateField(default=None, null=True, blank=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)

    objects = ResidentManager()

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.picture:
            img = Image.open(self.picture.path)
            if img.height > 800 or img.width > 800:
                output_size = (800, 800)
                img.thumbnail(output_size)
                img.save(self.picture.path)

    def __str__(self):
        return self.get_full_name()


class ResidentContact(models.Model):
    """
    Kontaktdaten der Erziehungsberechtigten und weiterer Bezugspersonen.

    Steht bewusst am Bewohner und nicht nur an der Fallakte: wenn nachts
    etwas passiert, muss die Nummer der Mutter auf der Bewohnerseite stehen
    und nicht drei Klicks tiefer im Hilfeplanverfahren. Die Beteiligten der
    Fallakte (django_grp_care.CaseParticipant) bleiben davon unberührt -
    dort geht es um das Verfahren, hier um die Erreichbarkeit.

    Sorgerecht und Notfallkontakt sind eigene Felder, weil beides im Alltag
    unterschiedliche Fragen beantwortet: wer darf entscheiden, und wen ruft
    man zuerst an. Das ist nicht immer dieselbe Person.
    """

    KIND_CHOICES = [
        ("guardian", "Erziehungsberechtigt"),
        ("mother", "Mutter"),
        ("father", "Vater"),
        ("custodian", "Vormund"),
        ("relative", "Angehörige:r"),
        ("youth_office", "Jugendamt"),
        ("doctor", "Ärztin / Arzt"),
        ("school", "Schule / Kita"),
        ("therapy", "Therapie"),
        ("other", "Sonstige"),
    ]

    resident = models.ForeignKey(
        Resident,
        on_delete=models.CASCADE,
        related_name="contacts",
        verbose_name="Bewohner:in",
        # Siehe Protocol.template: die Datenbank liegt auf einem Windows-
        # Bind-Mount, auf dem InnoDB keine Fremdschlüssel nachtragen kann.
        db_constraint=False,
    )
    kind = models.CharField(
        max_length=20,
        choices=KIND_CHOICES,
        default="guardian",
        verbose_name="Rolle",
    )
    name = models.CharField(max_length=120, verbose_name="Name")
    relationship = models.CharField(
        max_length=80,
        blank=True,
        default="",
        verbose_name="Verhältnis",
        help_text="Freitext, falls die Rolle es nicht genau trifft",
    )
    organisation = models.CharField(
        max_length=120, blank=True, default="", verbose_name="Organisation"
    )
    phone = models.CharField(
        max_length=40, blank=True, default="", verbose_name="Telefon"
    )
    mobile = models.CharField(
        max_length=40, blank=True, default="", verbose_name="Mobil"
    )
    email = models.EmailField(blank=True, default="", verbose_name="E-Mail")
    address = models.CharField(
        max_length=200, blank=True, default="", verbose_name="Anschrift"
    )
    has_custody = models.BooleanField(
        default=False,
        verbose_name="Sorgeberechtigt",
        help_text="Darf über Schule, Medizin und Aufenthalt mitentscheiden",
    )
    is_emergency = models.BooleanField(
        default=False,
        verbose_name="Notfallkontakt",
        help_text="Wird im Notfall zuerst angerufen",
    )
    note = models.TextField(
        blank=True,
        default="",
        verbose_name="Hinweis",
        help_text="Erreichbarkeit, Absprachen, Umgangsregelungen",
    )
    position = models.PositiveIntegerField(default=0, verbose_name="Reihenfolge")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Notfallkontakte zuerst, danach die eigene Reihenfolge - so steht
        # oben, was im Ernstfall gebraucht wird.
        ordering = ["-is_emergency", "position", "id"]
        verbose_name = "Kontakt"
        verbose_name_plural = "Kontakte"
        indexes = [models.Index(fields=["resident", "position"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_kind_display()})"

    @property
    def reachability(self) -> str:
        """Telefon, Mobil und E-Mail in einer Zeile - für Listen und PDF."""
        parts = [part for part in (self.phone, self.mobile, self.email) if part]
        return " · ".join(parts)


class Protocol(models.Model):
    STATUS_CHOICES = [
        ("draft", "Entwurf"),
        ("ready", "Bereit zum Export"),
        ("exported", "Exportiert"),
    ]

    protocol_date = models.DateField()
    date_added = models.DateField(auto_now_add=True)
    last_updated = models.DateField(auto_now=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    exported = models.BooleanField(default=False)
    exported_file = models.FileField(upload_to="exports/", blank=True, null=True)
    template = models.ForeignKey(
        "ProtocolTemplate",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="protocols",
        verbose_name="Vorlage",
        help_text="Protokolltyp, aus dem die Tagesordnung erzeugt wurde",
        db_constraint=False,
    )
    topic = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="Thema",
        help_text="Thema oder Anlass des Gruppenangebots",
    )

    objects = ProtocolManager()

    def __str__(self):
        return f"{self.group.name} - {self.protocol_date}"

    @property
    def is_exported(self):
        """Check if protocol is exported (read-only)."""
        return self.status == "exported"


class ProtocolPresence(models.Model):
    protocol = models.ForeignKey(
        Protocol,
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    was_present = models.BooleanField(default=False)

    class Meta:
        unique_together = ("protocol", "user")


class ProtocolItem(models.Model):
    """
    Ein Punkt der Tagesordnung.

    Historisch war `value` reines Markdown - Tabellen wurden als Pipe-Syntax
    hineingeschrieben. Mit `kind="table"` liegen Tabellen jetzt strukturiert in
    `data`, sodass die Oberflaeche einen echten Tabelleneditor anbieten kann.
    `value` bleibt fuer Fliesstext und fuer Altbestaende erhalten.
    """

    KIND_CHOICES = [
        ("text", "Freitext"),
        ("table", "Tabelle"),
    ]

    protocol = models.ForeignKey(
        Protocol, related_name="items", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100)
    position = models.IntegerField(default=0)
    value = models.TextField(blank=True, null=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="text")
    data = models.JSONField(
        blank=True,
        null=True,
        verbose_name="Strukturierter Inhalt",
        help_text='Bei kind="table": {"columns": [...], "rows": [[...], ...]}',
    )

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return f"{self.protocol} - {self.name}"


class UserPermission(models.Model):
    """
    Fine-grained permissions for users on specific resources.

    Allows staff to assign specific read/write permissions on:
    - Residents (create, read, update, delete)
    - Protocols (create, read, update, delete)
    - Groups (read, update)
    """

    PERMISSION_CHOICES = [
        ("read", "Lesezugriff"),
        ("write", "Schreibzugriff"),
        ("delete", "Löschzugriff"),
    ]

    RESOURCE_CHOICES = [
        ("resident", "Bewohner"),
        ("protocol", "Protokolle"),
        ("group", "Gruppen"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="permissions")
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    resource = models.CharField(max_length=20, choices=RESOURCE_CHOICES)
    permission = models.CharField(max_length=20, choices=PERMISSION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "group", "resource", "permission")
        ordering = ["user", "group", "resource"]

    def __str__(self):
        return f"{self.user.username} - {self.group.name} - {self.resource}: {self.permission}"


class ProtocolTodo(models.Model):
    """
    Todo items for protocols.

    Tracks tasks that need to be completed for a protocol:
    - what: What needs to be done
    - who: Who is responsible
    - when: When it's due
    """

    protocol = models.ForeignKey(
        Protocol, on_delete=models.CASCADE, related_name="todos"
    )
    what = models.TextField(verbose_name="What", help_text="What needs to be done")
    who = models.CharField(
        max_length=255, verbose_name="Who", help_text="Who is responsible"
    )
    when = models.DateTimeField(verbose_name="When", help_text="When it's due")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    position = models.IntegerField(default=0)

    class Meta:
        ordering = ["position", "when"]
        verbose_name = "Protocol Todo"
        verbose_name_plural = "Protocol Todos"

    def __str__(self) -> str:
        return f"{self.protocol} - {self.what[:50]}"


class ProtocolTemplate(models.Model):
    """
    Protokolltyp mit vorbereiteter Tagesordnung.

    Deckt Phase 6 der Roadmap ab: unterschiedliche Angebotsformen (Gruppenabend,
    Tagesgruppenangebot, Projektgruppe) brauchen unterschiedliche Gliederungen.
    Ohne `group` gilt die Vorlage traegerweit, mit `group` nur fuer diese Gruppe.
    """

    name = models.CharField(max_length=100, verbose_name="Name")
    description = models.CharField(
        max_length=200, blank=True, default="", verbose_name="Beschreibung"
    )
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="protocol_templates",
        verbose_name="Gruppe",
        help_text="Leer lassen, damit die Vorlage für alle Gruppen gilt",
        db_constraint=False,
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    position = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "name"]
        verbose_name = "Protokollvorlage"
        verbose_name_plural = "Protokollvorlagen"

    def __str__(self) -> str:
        scope = self.group.name if self.group else "alle Gruppen"
        return f"{self.name} ({scope})"


class ProtocolTemplateItem(models.Model):
    """Ein vorbereiteter Tagesordnungspunkt innerhalb einer Vorlage."""

    template = models.ForeignKey(
        ProtocolTemplate,
        related_name="items",
        on_delete=models.CASCADE,
        db_constraint=False,
    )
    name = models.CharField(max_length=100, verbose_name="Überschrift")
    position = models.IntegerField(default=0)
    kind = models.CharField(
        max_length=20, choices=ProtocolItem.KIND_CHOICES, default="text"
    )
    hint = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="Hinweis",
        help_text="Wird als Platzhalter im Editor angezeigt",
    )
    value = models.TextField(blank=True, default="", verbose_name="Vorbelegter Text")
    columns = models.JSONField(
        blank=True,
        null=True,
        verbose_name="Spalten",
        help_text='Bei kind="table", z. B. ["Aufgabe", "Verantwortung", "Termin"]',
    )
    rows = models.IntegerField(
        default=3,
        verbose_name="Leerzeilen",
        help_text="Vorbereitete Zeilen der Tabelle",
    )

    class Meta:
        ordering = ["position"]
        verbose_name = "Vorlagen-Baustein"
        verbose_name_plural = "Vorlagen-Bausteine"

    def __str__(self) -> str:
        return f"{self.template.name} - {self.name}"

    def build_data(self):
        """Startinhalt fuer einen daraus erzeugten Protokolleintrag."""
        if self.kind != "table":
            return None
        columns = self.columns or ["Spalte 1", "Spalte 2"]
        return {
            "columns": list(columns),
            "rows": [["" for _ in columns] for _ in range(max(1, self.rows))],
        }


class ProtocolAttendance(models.Model):
    """
    Teilnahme der Bewohner am Gruppenangebot.

    Ergaenzt ProtocolPresence: dort geht es um die anwesenden Mitarbeitenden,
    hier um die teilnehmenden Kinder und Jugendlichen.
    """

    protocol = models.ForeignKey(
        Protocol,
        related_name="attendances",
        on_delete=models.CASCADE,
        db_constraint=False,
    )
    resident = models.ForeignKey(
        Resident, on_delete=models.CASCADE, db_constraint=False
    )
    was_present = models.BooleanField(default=True, verbose_name="Teilgenommen")
    note = models.CharField(
        max_length=200, blank=True, default="", verbose_name="Anmerkung"
    )

    class Meta:
        unique_together = ("protocol", "resident")
        ordering = ["resident__last_name", "resident__first_name"]
        verbose_name = "Teilnahme"
        verbose_name_plural = "Teilnahmen"

    def __str__(self) -> str:
        return f"{self.protocol} - {self.resident}"


class ProtocolObservation(models.Model):
    """
    Verlaufsbericht zum Protokoll.

    Ohne `resident` beschreibt der Eintrag die Entwicklung der Gruppe, mit
    `resident` den Einzelverlauf einer Person (Roadmap Phase 6).
    """

    CATEGORY_CHOICES = [
        ("course", "Verlauf"),
        ("observation", "Beobachtung"),
        ("agreement", "Vereinbarung"),
    ]

    protocol = models.ForeignKey(
        Protocol,
        related_name="observations",
        on_delete=models.CASCADE,
        db_constraint=False,
    )
    resident = models.ForeignKey(
        Resident,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        verbose_name="Bewohner",
        help_text="Leer lassen für die Gruppe insgesamt",
        db_constraint=False,
    )
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default="course"
    )
    text = models.TextField(verbose_name="Text")
    position = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "Verlaufseintrag"
        verbose_name_plural = "Verlaufseinträge"

    def __str__(self) -> str:
        who = self.resident.get_full_name() if self.resident else "Gruppe"
        return f"{self.protocol} - {who}"


@receiver(post_save, sender=Protocol)
def create_protocol_presence(sender, instance, created, **kwargs):
    """
    Das Team der Gruppe steht von Anfang an im Protokoll.

    Wer zum Team gehoert, ist bekannt und aendert sich selten - die Liste
    braucht deshalb nur noch ein Ja/Nein je Person. Waere sie leer, muesste
    die Fachkraft abends erst ihre Kolleginnen zusammensuchen, um
    festzuhalten, wer da war.
    """
    if created:
        users_in_group = instance.group.group_members.all()
        for user in users_in_group:
            ProtocolPresence.objects.create(protocol=instance, user=user)


# Die Teilnehmenden entstehen NICHT automatisch.
#
# Frueher legte ein zweites Signal hier fuer jeden aktiven Bewohner der
# Gruppe einen Eintrag an, alle mit was_present=True. Das kehrt die Frage um:
# statt einzutragen, wer da war, musste man wegklicken, wer nicht da war -
# und wer das vergisst, hat eine Teilnahmeliste dokumentiert, die niemand je
# bestaetigt hat. Bei einem Angebot fuer drei von zwoelf Jugendlichen ist das
# schlicht falsch.
#
# Beim Team ist es umgekehrt richtig (siehe oben): dort steht die Runde
# vorher fest, hier nicht.


@receiver(post_save, sender=Protocol)
def apply_protocol_template(sender, instance, created, **kwargs):
    """Tagesordnung aus der gewaehlten Vorlage erzeugen."""
    if not created or not instance.template_id:
        return
    for item in instance.template.items.all():
        ProtocolItem.objects.create(
            protocol=instance,
            name=item.name,
            position=item.position,
            kind=item.kind,
            value=item.value or "",
            data=item.build_data(),
        )
