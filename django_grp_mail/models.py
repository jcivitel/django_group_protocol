"""
E-Mail-Versand: Einstellungen und Postausgang.

Zwei Modelle, die zusammengehoeren.

**MailSettings** haelt die Zugangsdaten zum Mailserver. Sie stehen bewusst in
der Datenbank und nicht in einer .env: die Verwaltung soll sie im Frontend
eintragen und dort auch pruefen koennen, ohne jemanden mit Serverzugang zu
brauchen. Das Passwort liegt verschluesselt (siehe crypto.py).

**MailMessage** ist der Postausgang. Jede Mail wird erst als Zeile
geschrieben und dann verschickt - nicht umgekehrt. Das kostet fast nichts und
bringt drei Dinge:

1. Man sieht, was rausging und was fehlschlug, ohne in ein Containerlog zu
   steigen.
2. Eine gescheiterte Mail laesst sich erneut senden, statt verloren zu sein.
3. Faellt der Broker aus, ist die Mail trotzdem festgehalten - der Worker
   holt sie nach.
"""

from django.db import models

from .crypto import entschluesseln, verschluesseln


class MailSettings(models.Model):
    """
    Zugangsdaten zum Mailserver. Es gibt genau einen Satz davon.

    Kein Singleton-Zwang per Datenbank-Constraint, sondern per laden():
    ein zweiter Datensatz waere kein Fehler, der etwas kaputt macht, sondern
    einer, den niemand je zu Gesicht bekommt.
    """

    host = models.CharField(max_length=200, blank=True, default="", verbose_name="Server")
    port = models.PositiveIntegerField(default=587, verbose_name="Port")
    use_tls = models.BooleanField(
        default=True,
        verbose_name="STARTTLS",
        help_text="Der uebliche Weg auf Port 587",
    )
    use_ssl = models.BooleanField(
        default=False,
        verbose_name="SSL",
        help_text="Nur fuer Port 465 - nicht zusammen mit STARTTLS",
    )
    username = models.CharField(
        max_length=200, blank=True, default="", verbose_name="Benutzername"
    )
    password_encrypted = models.TextField(blank=True, default="", editable=False)
    from_address = models.EmailField(
        blank=True, default="", verbose_name="Absenderadresse"
    )
    from_name = models.CharField(
        max_length=120,
        blank=True,
        default="Gruppenprotokoll",
        verbose_name="Absendername",
    )
    timeout_seconds = models.PositiveIntegerField(
        default=15, verbose_name="Zeitgrenze in Sekunden"
    )
    enabled = models.BooleanField(
        default=False,
        verbose_name="Versand aktiv",
        help_text="Aus heisst: Mails werden im Postausgang festgehalten, aber nicht verschickt",
    )

    # --- Push. Steht hier und nicht in einem eigenen Modell: es ist
    # dieselbe Frage - wie erreicht die Anwendung jemanden -, nur ein
    # anderer Weg. Zwei Einstellungsseiten fuer eine Frage waeren eine
    # zu viel.
    push_enabled = models.BooleanField(
        default=False,
        verbose_name="Push aktiv",
        help_text="Benachrichtigungen auf Telefon und Rechner, zusätzlich zur E-Mail",
    )
    vapid_public_key = models.TextField(
        blank=True,
        default="",
        verbose_name="Öffentlicher Schlüssel",
        help_text="Wird an den Browser gegeben – kein Geheimnis",
    )
    vapid_private_key_encrypted = models.TextField(
        blank=True, default="", editable=False
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "E-Mail-Einstellung"
        verbose_name_plural = "E-Mail-Einstellungen"

    def __str__(self) -> str:
        return self.host or "noch nicht eingerichtet"

    @classmethod
    def laden(cls) -> "MailSettings":
        """Der eine Datensatz, notfalls frisch angelegt."""
        eintrag = cls.objects.order_by("id").first()
        if eintrag is None:
            eintrag = cls.objects.create()
        return eintrag

    @property
    def password(self) -> str:
        return entschluesseln(self.password_encrypted)

    @password.setter
    def password(self, klartext: str) -> None:
        self.password_encrypted = verschluesseln(klartext)

    @property
    def has_password(self) -> bool:
        return bool(self.password_encrypted)

    @property
    def absender(self) -> str:
        """"Name <adresse>" oder nur die Adresse."""
        if self.from_name and self.from_address:
            return f"{self.from_name} <{self.from_address}>"
        return self.from_address

    @property
    def ready(self) -> bool:
        """Reicht das zum Verschicken?"""
        return bool(self.enabled and self.host and self.from_address)

    @property
    def vapid_private_key(self) -> str:
        return entschluesseln(self.vapid_private_key_encrypted)

    @vapid_private_key.setter
    def vapid_private_key(self, klartext: str) -> None:
        self.vapid_private_key_encrypted = verschluesseln(klartext)

    @property
    def has_vapid_keys(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key_encrypted)

    @property
    def push_ready(self) -> bool:
        return bool(self.push_enabled and self.has_vapid_keys)


class MailMessage(models.Model):
    """Eine Mail im Postausgang."""

    STATUS_CHOICES = [
        ("queued", "Wartet"),
        ("sending", "Wird verschickt"),
        ("sent", "Verschickt"),
        ("failed", "Fehlgeschlagen"),
        ("skipped", "Übersprungen"),
    ]

    # Wofuer die Mail steht. Nur zur Einordnung im Postausgang - der Versand
    # unterscheidet nicht danach.
    KIND_CHOICES = [
        ("test", "Testmail"),
        ("absence_decided", "Abwesenheit entschieden"),
        ("plan_published", "Dienstplan veröffentlicht"),
        ("swap", "Diensttausch"),
        ("todo_due", "Aufgabe wird fällig"),
    ]

    to_address = models.EmailField(verbose_name="Empfänger")
    subject = models.CharField(max_length=250, verbose_name="Betreff")
    body = models.TextField(verbose_name="Inhalt")
    kind = models.CharField(
        max_length=30, choices=KIND_CHOICES, default="test", verbose_name="Anlass"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="queued", verbose_name="Stand"
    )
    error = models.TextField(blank=True, default="", verbose_name="Fehler")
    attempts = models.PositiveIntegerField(default=0, verbose_name="Versuche")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(blank=True, null=True, verbose_name="Verschickt am")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Postausgang"
        verbose_name_plural = "Postausgang"
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self) -> str:
        return f"{self.to_address}: {self.subject}"


class PushSubscription(models.Model):
    """
    Ein Geraet, das Benachrichtigungen empfangen will.

    Mehrere je Person sind der Normalfall: Diensthandy und privates Telefon,
    dazu der Rechner im Buero. Der endpoint ist die Adresse beim Push-Dienst
    des Browserherstellers und zugleich der Schluessel - dasselbe Geraet
    meldet sich mit derselben Adresse wieder an, statt eine zweite Zeile
    anzulegen.

    Die beiden Schluessel sind keine Geheimnisse im ueblichen Sinn: sie
    gehoeren zu genau diesem Geraet und taugen nur dafuer, ihm etwas zu
    schicken. Sie stehen deshalb im Klartext.
    """

    user = models.ForeignKey(
        "auth.User",
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
        verbose_name="Konto",
    )
    endpoint = models.TextField(unique=True, verbose_name="Adresse")
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(
        max_length=250,
        blank=True,
        default="",
        verbose_name="Gerät",
        help_text="Damit man in der Liste erkennt, welches Gerät gemeint ist",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Push-Anmeldung"
        verbose_name_plural = "Push-Anmeldungen"

    def __str__(self) -> str:
        return f"{self.user} – {self.user_agent or self.endpoint[:40]}"
