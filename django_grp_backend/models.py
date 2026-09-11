import os
import random
import uuid

from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.deconstruct import deconstructible

from django_grp_backend.access import is_admin
from django_grp_backend.bilder import einplanen
from django_grp_backend.functions import validate_image
from datetime import date

# db_constraint=False ist entfallen.
#
# Der Grund dafuer war ein Windows-Bind-Mount als Datenverzeichnis von
# MariaDB (./mysql:/var/lib/mysql in utils/docker-compose.yml): InnoDB kann
# Dateien darauf nicht umbenennen, und jedes "ALTER TABLE ... ADD FOREIGN
# KEY" brach mit "Tablespace is missing" ab.
#
# Das docker-compose dieses Projekts nutzt ein Named Volume. Der Workaround
# war damit ueberholt und kostete nur noch referenzielle Integritaet: ohne
# Constraint bleiben nach einem geloeschten Bewohner verwaiste Teilnahmen
# stehen, und niemand merkt es, bis eine Auswertung sie zaehlt.

# ============ CUSTOM QUERYSETS ============


def traeger_filter(user):
    """
    Traegergrenze fuer Gruppen - als Q-Objekt.

    Gruppen haengen ueber `Department.group` an der Organisationsstruktur:
    Bereich -> Einrichtung -> Standort -> Traeger. Wer einen Personaldatensatz
    hat, soll nur die Gruppen seines Traegers sehen; das galt in `org`, `duty`
    und `care` laengst, in der Kern-App aber nicht - ein Verwaltungskonto sah
    jede Gruppe jedes Traegers (Analyse 6.4).

    Zwei Faelle bleiben ausdruecklich offen:

    - Gruppen OHNE Bereichsverknuepfung. Die gibt es in jedem gewachsenen
      Bestand, und sie ploetzlich verschwinden zu lassen hiesse, die
      Anwendung nach einem Update leer aussehen zu lassen.
    - Konten ohne Personaldatensatz. Solange nicht jedes Konto einem Traeger
      zugeordnet ist, waere die Trennung eine Aussperrung. STRICT_TENANCY
      schaltet auch das scharf, sobald der Bestand so weit ist.

    Der Import steht in der Funktion: django_grp_backend darf
    django_grp_org nicht zur Ladezeit brauchen - sonst schliesst sich der
    Ring zwischen den beiden Apps.
    """
    from django.conf import settings
    from django_grp_org.tenancy import visible_provider_ids

    provider_ids = visible_provider_ids(user)
    if provider_ids is None:
        if getattr(settings, "STRICT_TENANCY", False) and not getattr(
            user, "is_superuser", False
        ):
            # Kein Personaldatensatz, kein Traeger, keine Gruppen.
            return models.Q(pk__in=[])
        return models.Q()

    return models.Q(
        departments__facility__site__provider_id__in=provider_ids
    ) | models.Q(departments__isnull=True)


class GroupQuerySet(models.QuerySet):
    """Custom QuerySet for Group model."""

    def for_user(self, user):
        """Gruppen, die das Konto sehen darf."""
        if is_admin(user):
            # Auch die Verwaltung sieht nur den eigenen Traeger. "Alles" hiess
            # hier bisher woertlich alles - ueber Traegergrenzen hinweg.
            return self.filter(traeger_filter(user)).distinct()
        return self.filter(group_members=user)


class ResidentQuerySet(models.QuerySet):
    """Custom QuerySet for Resident model."""

    def for_user(self, user):
        """Bewohner der Gruppen, die das Konto sehen darf."""
        if is_admin(user):
            return self.filter(
                group__in=Group.objects.for_user(user)
            ).distinct()
        return self.filter(group__group_members=user)

    def active(self):
        """Return only active residents (not moved out)."""
        return self.filter(moved_out_since__isnull=True)


class ProtocolQuerySet(models.QuerySet):
    """Custom QuerySet for Protocol model."""

    def for_user(self, user):
        """Protokolle der Gruppen, die das Konto sehen darf."""
        if is_admin(user):
            return self.filter(
                group__in=Group.objects.for_user(user)
            ).distinct()
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
    # Sage aus der Palette statt Weiss. Die alte Vorgabe war auf hellem
    # Grund unsichtbar - eine Gruppe ohne gewaehlte Farbe hatte damit gar
    # keine Kennfarbe, sondern nur eine unsichtbare.
    color = models.CharField(max_length=9, default="#abc270")
    group_members = models.ManyToManyField(User, blank=True)
    pdf_template = models.FileField(upload_to="docs/", blank=True, null=True)

    # Wo auf der Vorlage gedruckt werden darf, in PDF-Punkten vom jeweiligen
    # Rand (72 Punkt = 1 Zoll = 25,4 mm).
    #
    # Ohne das beginnt der Text 56 Punkt unter der Oberkante - und landet
    # bei jedem Briefkopf mitten im Logo. Die Werte stehen an der Gruppe und
    # nicht global, weil jeder Traeger sein eigenes Papier hat und manche
    # Gruppen ein eigenes.
    pdf_top = models.FloatField(default=56, verbose_name="Abstand oben")
    pdf_right = models.FloatField(default=56, verbose_name="Abstand rechts")
    pdf_bottom = models.FloatField(default=56, verbose_name="Abstand unten")
    pdf_left = models.FloatField(default=56, verbose_name="Abstand links")

    objects = GroupManager()

    class Meta:
        # Ohne feste Sortierung ist eine seitenweise Antwort nicht stabil:
        # die Datenbank darf die Reihenfolge zwischen zwei Abfragen aendern,
        # und dann steht derselbe Datensatz auf Seite 1 und Seite 2 - oder
        # auf keiner.
        ordering = ["name", "id"]
        verbose_name = "Gruppe"
        verbose_name_plural = "Gruppen"

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
    # Geschlecht nach den Kategorien der amtlichen Kinder- und Jugendhilfe-
    # statistik (§ 99 SGB VIII). Leer heisst "ohne Angabe" und ist dort eine
    # eigene, zulaessige Auspraegung - deshalb kein Zwang und keine Vorgabe.
    GENDER_CHOICES = [
        ("female", "Weiblich"),
        ("male", "Männlich"),
        ("diverse", "Divers"),
    ]

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    birth_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="Geburtsdatum",
        help_text="Grundlage des Alters in der amtlichen Statistik",
    )
    gender = models.CharField(
        max_length=10,
        choices=GENDER_CHOICES,
        blank=True,
        default="",
        verbose_name="Geschlecht",
        help_text="Leer lassen, wenn keine Angabe vorliegt",
    )
    picture = models.ImageField(
        blank=True,
        null=True,
        upload_to=RandomizedFileName(),
        validators=[validate_image],
    )
    school = models.CharField(
        max_length=150,
        blank=True,
        default="",
        verbose_name="Schule",
        help_text="Der zweite Lebensmittelpunkt und der häufigste Anlass für Absprachen",
    )
    school_class = models.CharField(
        max_length=30, blank=True, default="", verbose_name="Klasse"
    )
    school_contact = models.CharField(
        max_length=150,
        blank=True,
        default="",
        verbose_name="Klassenleitung",
        help_text="Name und Erreichbarkeit",
    )
    moved_in_since = models.DateField()
    moved_out_since = models.DateField(default=None, null=True, blank=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)

    objects = ResidentManager()

    class Meta:
        # Nach Nachnamen, wie in jeder Liste im Haus - und mit der Nummer als
        # Gleichstand, damit die Sortierung eindeutig ist (Pagination).
        ordering = ["last_name", "first_name", "id"]
        verbose_name = "Bewohner"
        verbose_name_plural = "Bewohner"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

    def save(self, *args, **kwargs):
        """
        Speichern, das Verkleinern des Fotos danach.

        Vorher stand hier `Image.open(...).thumbnail(...).save(...)` mitten im
        Request: die Fachkraft, die ein Foto hochlaedt, wartete auf das
        Dekodieren und Zurueckschreiben eines Mehrmegabyte-Bildes. Jetzt
        uebernimmt das Celery, und faellt der Broker aus, passiert es wie
        bisher direkt - nur eben als bewusster Rueckfall.
        """
        super().save(*args, **kwargs)
        einplanen(self.picture)

    def __str__(self):
        return self.get_full_name()


    @property
    def age(self) -> int | None:
        """
        Alter in vollen Jahren, oder None ohne Geburtsdatum.

        Gerechnet und nicht gespeichert: ein Alter altert, waehrend niemand
        hinsieht.
        """
        if not self.birth_date:
            return None
        heute = date.today()
        jahre = heute.year - self.birth_date.year
        # Noch nicht Geburtstag gehabt? Dann ein Jahr weniger.
        if (heute.month, heute.day) < (self.birth_date.month, self.birth_date.day):
            jahre -= 1
        return jahre


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
    # Abgeleitet aus status, siehe save(). Das Feld ist aelter als die
    # Statuskette und meint dasselbe wie status == "exported"; zwei Felder
    # fuer denselben Sachverhalt gehen frueher oder spaeter auseinander, und
    # dann glaubt die eine Haelfte des Codes das eine und die andere das
    # andere. Es bleibt bestehen, weil Auswertungen und Filter darauf
    # zeigen - aber es wird nicht mehr von aussen gesetzt.
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
    )
    topic = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="Thema",
        help_text="Thema oder Anlass des Gruppenangebots",
    )

    objects = ProtocolManager()

    class Meta:
        # Das juengste zuerst - so, wie die Liste im Frontend es zeigt.
        ordering = ["-protocol_date", "-id"]
        verbose_name = "Protokoll"
        verbose_name_plural = "Protokolle"

    def save(self, *args, **kwargs):
        """
        Haelt `exported` und `status` zusammen.

        Es gibt genau eine Wahrheit darueber, ob ein Protokoll abgeschlossen
        ist, und die steht in `status`. `exported` folgt ihr - hier, an einer
        Stelle, statt an jedem Aufrufer.
        """
        self.exported = self.status == "exported"

        # update_fields nachziehen: sonst wird die Angleichung still
        # verworfen, wenn jemand gezielt nur `status` speichert.
        felder = kwargs.get("update_fields")
        if felder is not None:
            felder = set(felder)
            if "status" in felder:
                felder.add("exported")
            kwargs["update_fields"] = felder

        super().save(*args, **kwargs)

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
        # Feste Reihenfolge, damit eine seitenweise Antwort stabil bleibt.
        ordering = ["id"]
        verbose_name = "Anwesenheit"
        verbose_name_plural = "Anwesenheiten"


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
        ("medication", "Medikationsübersicht"),
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


# UserPermission ist entfallen.
#
# Das Modell trug eine feingranulare Rechtematrix (Bewohner/Protokolle/
# Gruppen mal lesen/schreiben/loeschen, je Gruppe). Ausgewertet hat sie kein
# einziger Endpunkt: wer in der Oberflaeche jemanden auf "nur lesen" stellte,
# glaubte es habe gewirkt - es hatte nicht. Was wirklich gilt, stehen die
# drei Stufen in django_grp_backend/access.py.
#
# Ein Modell, das eine Rechtevergabe vortaeuscht, ist schlimmer als keines.


class ProtocolTodo(models.Model):
    """
    Todo items for protocols.

    Tracks tasks that need to be completed for a protocol:
    - what: What needs to be done
    - who: Who is responsible
    - when: When it's due
    - done_at: Wann sie erledigt wurde; leer heisst offen

    **`done_at` als Zeitpunkt und nicht als Haekchen.** Eine Aufgabe aus
    einem Protokoll ist Teil der Dokumentation: bei einer Rueckfrage zaehlt,
    wann etwas getan wurde, nicht nur dass es getan wurde. Ein Wahrheitswert
    verliert genau die Angabe, die man spaeter braucht.

    Anders als eine Medikamentengabe laesst sich das wieder aufheben. Wer
    versehentlich abhakt, hakt wieder ab - eine Aufgabe ist kein Nachweis
    einer Handlung am Kind, sondern eine Merkliste.
    """

    protocol = models.ForeignKey(
        Protocol, on_delete=models.CASCADE, related_name="todos"
    )
    what = models.TextField(verbose_name="What", help_text="What needs to be done")
    who = models.CharField(
        max_length=255, verbose_name="Who", help_text="Who is responsible"
    )
    when = models.DateTimeField(verbose_name="When", help_text="When it's due")
    done_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Erledigt am",
        help_text="Leer heißt: noch offen",
    )
    done_by = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="Erledigt von",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    position = models.IntegerField(default=0)

    class Meta:
        # Offene zuerst, danach nach Frist. Eine erledigte Aufgabe zwischen
        # zwei offenen ist Laerm in einer Liste, die zum Abarbeiten da ist.
        ordering = ["position", "when"]
        verbose_name = "Protocol Todo"
        verbose_name_plural = "Protocol Todos"

    def __str__(self) -> str:
        return f"{self.protocol} - {self.what[:50]}"

    @property
    def is_done(self) -> bool:
        return self.done_at is not None

    @property
    def is_overdue(self) -> bool:
        """Ueberfaellig ist nur, was offen ist - das war der ganze Fehler."""
        if self.done_at is not None:
            return False
        return self.when < timezone.now()


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
    )
    resident = models.ForeignKey(
        Resident, on_delete=models.CASCADE
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
    )
    resident = models.ForeignKey(
        Resident,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        verbose_name="Bewohner",
        help_text="Leer lassen für die Gruppe insgesamt",
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


def medikationsuebersicht(group) -> dict:
    """
    Der Medikationsplan einer Gruppe als Momentaufnahme.

    **Warum eingefroren und nicht live.** Ein Protokoll ist ein Nachweis.
    Wuerde dieser Baustein beim Lesen die heutige Medikation zeigen, stuende
    im Protokoll vom Maerz die Lage vom September - und die Frage "was
    wussten wir damals" waere nicht mehr zu beantworten. Der Plan wird
    deshalb beim Anlegen des Protokolls abgeschrieben und bleibt dann stehen.

    Aufgenommen wird nur, was an diesem Tag gilt, und nur je Wirkstoff eine
    Zeile. Wer das ganze Archiv eines Kindes in jede Teambesprechung legt,
    legt ein Dokument an, das niemand liest.
    """
    from .akte import Medication

    heute = date.today()
    zeilen = []
    laufend = (
        Medication.objects.filter(resident__group=group)
        .filter(valid_from__lte=heute)
        .filter(models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=heute))
        .filter(resident__moved_out_since__isnull=True)
        .select_related("resident")
        .order_by("resident__last_name", "resident__first_name", "agent")
    )
    for eintrag in laufend:
        zeiten = ", ".join(eintrag.times) if eintrag.times else ""
        if eintrag.as_needed:
            zeiten = "nach Bedarf" if not zeiten else f"{zeiten}, nach Bedarf"
        zeilen.append(
            [
                eintrag.resident.get_full_name(),
                eintrag.agent,
                eintrag.dose,
                zeiten,
                eintrag.note,
            ]
        )

    return {
        "columns": ["Bewohner:in", "Wirkstoff", "Dosis", "Zeiten", "Hinweis"],
        "rows": zeilen,
        # Damit spaeter niemand raet, wann diese Zeilen entstanden sind.
        "stand": heute.isoformat(),
    }


@receiver(post_save, sender=Protocol)
def apply_protocol_template(sender, instance, created, **kwargs):
    """Tagesordnung aus der gewaehlten Vorlage erzeugen."""
    if not created or not instance.template_id:
        return
    for item in instance.template.items.all():
        if item.kind == "medication":
            daten = medikationsuebersicht(instance.group)
        else:
            daten = item.build_data()
        ProtocolItem.objects.create(
            protocol=instance,
            name=item.name,
            position=item.position,
            kind=item.kind,
            value=item.value or "",
            data=daten,
        )


class Allergy(models.Model):
    """
    Eine Allergie oder Unvertraeglichkeit.

    Steht am Bewohner und nicht in der Fallakte, und das ist der ganze Punkt:
    eine Allergie, die drei Klicks tief liegt, findet im Nachtdienst niemand.
    Sie erscheint deshalb in der Kopfzeile der Bewohnerseite, ohne dass man
    einen Reiter oeffnen muss.

    Eine Diagnose gehoert dagegen NICHT hierher. Sie ist ein Gesundheitsdatum
    nach Art. 9 DSGVO und gehoert in die Fallakte, wo der Zugriff enger ist.
    Der Unterschied ist praktisch: die Allergie braucht der Nachtdienst, die
    Diagnose nicht.
    """

    KIND_CHOICES = [
        ("food", "Lebensmittel"),
        ("medication", "Medikament"),
        ("insect", "Insektenstich"),
        ("material", "Material oder Stoff"),
        ("other", "Sonstiges"),
    ]

    # Die Schwere entscheidet ueber die Farbe in der Kopfzeile. Nur "severe"
    # bekommt Terrakotta - eine Warnfarbe, die ueberall steht, ist keine.
    SEVERITY_CHOICES = [
        ("mild", "Leicht"),
        ("moderate", "Mittel"),
        ("severe", "Schwer"),
    ]

    resident = models.ForeignKey(
        Resident,
        on_delete=models.CASCADE,
        related_name="allergies",
        verbose_name="Bewohner:in",
    )
    kind = models.CharField(
        max_length=20,
        choices=KIND_CHOICES,
        default="food",
        verbose_name="Art",
    )
    name = models.CharField(
        max_length=120,
        verbose_name="Bezeichnung",
        help_text="Woran genau, z. B. Erdnuss oder Penicillin",
    )
    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default="moderate",
        verbose_name="Schwere",
    )
    reaction = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="Reaktion",
        help_text="Was passiert, woran man es erkennt",
    )
    note = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="Hinweis",
        help_text="Was im Ernstfall zu tun ist",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Das Schwerste zuerst: wer die Liste ueberfliegt, sieht zuerst das,
        # was zaehlt.
        ordering = ["-severity", "name"]
        verbose_name = "Allergie"
        verbose_name_plural = "Allergien"

    def __str__(self) -> str:
        return f"{self.resident.get_full_name()}: {self.name}"

    @property
    def is_critical(self) -> bool:
        return self.severity == "severe"


class Consent(models.Model):
    """
    Eine Einwilligung der Sorgeberechtigten.

    Die Frage im Alltag lautet nicht "gibt es eine Einwilligung", sondern
    "darf ich dieses Kind heute mit ins Schwimmbad nehmen". Darauf muss die
    Anwendung in zwei Sekunden antworten - deshalb `status` als abgeleitete
    Angabe und nicht als Feld, das jemand pflegen muesste.

    Eine Einwilligung ist widerruflich (Art. 7 Abs. 3 DSGVO) und laeuft oft
    ab. Beides steht hier, und beides zaehlt: ein Widerruf schlaegt jede
    Laufzeit.

    **Widerruf loescht nicht.** Wer widerruft, hinterlaesst eine Zeile mit
    Datum. Die Einwilligung von damals hat gegolten, und dass sie gegolten
    hat, kann spaeter die entscheidende Frage sein.
    """

    SUBJECT_CHOICES = [
        ("photo_internal", "Fotos intern"),
        ("photo_external", "Fotos veröffentlichen"),
        ("outing", "Ausflüge und Fahrten"),
        ("swimming", "Schwimmen"),
        ("medical", "Ärztliche Behandlung"),
        ("medication", "Medikamentengabe"),
        ("data_school", "Austausch mit der Schule"),
        ("data_therapy", "Austausch mit Therapie und Medizin"),
        ("transport", "Mitfahrt im Dienstfahrzeug"),
        ("other", "Sonstiges"),
    ]

    resident = models.ForeignKey(
        Resident,
        on_delete=models.CASCADE,
        related_name="consents",
        verbose_name="Bewohner:in",
    )
    subject = models.CharField(
        max_length=30,
        choices=SUBJECT_CHOICES,
        verbose_name="Gegenstand",
    )
    granted = models.BooleanField(
        default=True,
        verbose_name="Erteilt",
        help_text="Nein heißt: ausdrücklich nicht erteilt. Das ist etwas anderes als „nicht gefragt“.",
    )
    granted_by = models.CharField(
        max_length=120,
        verbose_name="Erteilt von",
        help_text="Wer unterschrieben hat",
    )
    granted_on = models.DateField(verbose_name="Erteilt am")
    valid_until = models.DateField(
        blank=True,
        null=True,
        verbose_name="Gültig bis",
        help_text="Leer heißt: bis zum Widerruf",
    )
    revoked_on = models.DateField(
        blank=True,
        null=True,
        verbose_name="Widerrufen am",
    )
    note = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="Vermerk",
        help_text="Einschränkungen, Absprachen, wo das Papier liegt",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["subject", "-granted_on"]
        verbose_name = "Einwilligung"
        verbose_name_plural = "Einwilligungen"

    def __str__(self) -> str:
        return f"{self.resident.get_full_name()}: {self.get_subject_display()}"

    @property
    def status(self) -> str:
        """
        Gilt sie heute?

        Die Reihenfolge der Pruefungen ist die Aussage: ein Widerruf schlaegt
        alles, dann erst zaehlen Laufzeit und Erteilung.
        """
        from datetime import date as _date

        heute = _date.today()
        if self.revoked_on and self.revoked_on <= heute:
            return "revoked"
        if not self.granted:
            return "denied"
        if self.granted_on > heute:
            return "pending"
        if self.valid_until and self.valid_until < heute:
            return "expired"
        return "valid"

    @property
    def status_display(self) -> str:
        return {
            "valid": "Gültig",
            "expired": "Abgelaufen",
            "revoked": "Widerrufen",
            "denied": "Nicht erteilt",
            "pending": "Gilt ab später",
        }[self.status]


class ZweiterFaktor(models.Model):
    """
    Der zeitbasierte Einmalcode eines Kontos.

    Optional, wie entschieden: wer will, schaltet ihn ein. Pflicht ist er nur
    fuer Konten, die verwalten duerfen - siehe `rechte.zweitfaktor_pflicht`.
    Das ist kein Zufall, sondern die Gegenseite der zweiten Entscheidung: es
    gibt keine Wiederherstellungscodes, die Verwaltung setzt zurueck. Damit
    ist jedes Konto, das zuruecksetzen darf, ein Weg am Faktor vorbei - und
    genau deshalb muss es selbst einen haben.

    Das Geheimnis steht verschluesselt, aus demselben Grund wie das
    SMTP-Passwort: im Klartext stuende es in jedem Datenbank-Abzug, und die
    wandern erfahrungsgemaess herum. Wer die .env hat, kommt daran - das ist
    kein Tresor, aber es haelt den Schluessel aus Kopien heraus.

    Angelegt heisst nicht aktiv. Zwischen "eingerichtet" und "bestaetigt"
    liegt genau ein Schritt: ein Code, der stimmt. Ohne diese Trennung
    koennte sich jemand aussperren, indem er die Einrichtung abbricht,
    nachdem der Schluessel schon steht.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="zweiter_faktor",
        verbose_name="Konto",
    )
    geheim_verschluesselt = models.TextField(blank=True, default="", editable=False)

    bestaetigt_am = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Bestätigt am",
        help_text="Leer, solange die Einrichtung nicht abgeschlossen ist",
    )

    # Die Zeitscheibe der letzten erfolgreichen Anmeldung. Verhindert, dass
    # derselbe Code in denselben dreissig Sekunden zweimal gilt - wer einer
    # Fachkraft ueber die Schulter sieht, kaeme sonst direkt hinterher rein.
    letzter_schritt = models.BigIntegerField(blank=True, null=True, editable=False)

    erstellt_am = models.DateTimeField(auto_now_add=True)
    zuletzt_verwendet = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "Zweiter Faktor"
        verbose_name_plural = "Zweite Faktoren"

    def __str__(self) -> str:
        stand = "aktiv" if self.ist_aktiv else "eingerichtet, nicht bestätigt"
        return f"{self.user.username}: {stand}"

    @property
    def geheimnis(self) -> str:
        from django_grp_mail.crypto import entschluesseln

        return entschluesseln(self.geheim_verschluesselt)

    @geheimnis.setter
    def geheimnis(self, klartext: str) -> None:
        from django_grp_mail.crypto import verschluesseln

        self.geheim_verschluesselt = verschluesseln(klartext)

    @property
    def ist_aktiv(self) -> bool:
        """
        Nur ein bestaetigter Faktor zaehlt.

        Ein angelegter, aber nie bestaetigter Datensatz darf die Anmeldung
        nicht aufhalten - sonst sperrt eine abgebrochene Einrichtung das
        Konto aus.
        """
        return self.bestaetigt_am is not None and bool(self.geheim_verschluesselt)


# Die uebrige Bewohnerakte. Am Ende, weil sie Resident von hier braucht.
from .akte import (  # noqa: E402,F401
    ChecklistItem,
    Incident,
    Medication,
    MedicationAdministration,
    PocketMoneyEntry,
    ResidentAbsence,
)
