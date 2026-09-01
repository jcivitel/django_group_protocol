"""
Nachvollziehbarkeit sensibler Änderungen.

Roadmap Phase 1 verlangt „Event-Logging bei sensiblen Stammdatenänderungen",
Phase 9 „Logging, Monitoring und Fehlerbehandlung im Produktivbetrieb".

Protokolliert werden Personaldaten, Verträge, Rollen, Stellenbesetzungen und
die Fallführung - also alles, wo eine spätere Frage „wer hat das wann
geändert" berechtigt ist. Fachdaten des Alltags (Protokolleinträge,
Zeitbuchungen) bleiben außen vor; die stünden sonst zu Tausenden im Log und
sind über ihre eigenen Zeitstempel nachvollziehbar.

Der Benutzer kommt aus dem laufenden Request. Dafür hinterlegt eine
Middleware ihn in einem contextvar - Signale kennen den Request sonst nicht.
"""

import contextvars
import logging

from django.db import models
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

logger = logging.getLogger("django_grp.audit")

# Der Benutzer des laufenden Requests, gesetzt von AuditUserMiddleware.
_current_user = contextvars.ContextVar("audit_user", default=None)


def set_current_user(user):
    return _current_user.set(user)


def reset_current_user(token):
    _current_user.reset(token)


def get_current_user():
    user = _current_user.get()
    return user if user and getattr(user, "is_authenticated", False) else None


class AuditEvent(models.Model):
    """Ein einzelner Änderungsvorgang."""

    ACTION_CHOICES = [
        ("create", "Angelegt"),
        ("update", "Geändert"),
        ("delete", "Gelöscht"),
    ]

    model = models.CharField(max_length=100, verbose_name="Datensatzart")
    object_id = models.CharField(max_length=40, verbose_name="Datensatz")
    label = models.CharField(max_length=200, verbose_name="Bezeichnung")
    action = models.CharField(
        max_length=10, choices=ACTION_CHOICES, verbose_name="Vorgang"
    )
    changes = models.JSONField(
        blank=True,
        null=True,
        verbose_name="Änderungen",
        help_text='{"feld": ["vorher", "nachher"]}',
    )
    username = models.CharField(
        max_length=150, blank=True, default="", verbose_name="Benutzer"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Zeitpunkt")

    class Meta:
        app_label = "django_grp_org"
        ordering = ["-created_at"]
        verbose_name = "Änderungsprotokoll"
        verbose_name_plural = "Änderungsprotokoll"
        indexes = [models.Index(fields=["model", "object_id"])]

    def __str__(self) -> str:
        return f"{self.get_action_display()} {self.model} {self.label}"


# Welche Modelle beobachtet werden und welche Felder dabei uninteressant sind.
WATCHED = {
    "django_grp_org.Employee",
    "django_grp_org.Contract",
    "django_grp_org.Role",
    "django_grp_org.PositionAssignment",
    "django_grp_org.Position",
    "django_grp_care.CaseFile",
    "django_grp_care.HelpPlan",
}

IGNORED_FIELDS = {"id", "created_at", "updated_at"}


def _label(instance) -> str:
    try:
        return str(instance)[:200]
    except Exception:  # noqa: BLE001 - ein kaputtes __str__ darf nichts kippen
        return f"#{instance.pk}"


def _key(instance) -> str:
    return f"{instance._meta.app_label}.{instance._meta.object_name}"


def _values(instance) -> dict:
    data = {}
    for field in instance._meta.fields:
        if field.name in IGNORED_FIELDS:
            continue
        try:
            value = getattr(instance, field.attname)
        except Exception:  # noqa: BLE001
            continue
        data[field.name] = None if value is None else str(value)
    return data


@receiver(pre_save)
def remember_previous(sender, instance, **kwargs):
    """Alten Stand merken, damit post_save die Differenz bilden kann."""
    if _key(instance) not in WATCHED or instance.pk is None:
        return
    try:
        instance._audit_previous = _values(sender.objects.get(pk=instance.pk))
    except sender.DoesNotExist:
        instance._audit_previous = None


@receiver(post_save)
def record_save(sender, instance, created, **kwargs):
    key = _key(instance)
    if key not in WATCHED:
        return

    user = get_current_user()
    username = user.get_username() if user else ""

    if created:
        _write(key, instance, "create", None, username)
        return

    previous = getattr(instance, "_audit_previous", None)
    current = _values(instance)
    if previous is None:
        _write(key, instance, "update", None, username)
        return

    changes = {
        field: [previous.get(field), current.get(field)]
        for field in current
        if previous.get(field) != current.get(field)
    }
    if not changes:
        return
    _write(key, instance, "update", changes, username)


@receiver(post_delete)
def record_delete(sender, instance, **kwargs):
    key = _key(instance)
    if key not in WATCHED:
        return
    user = get_current_user()
    _write(key, instance, "delete", None, user.get_username() if user else "")


def _write(key, instance, action, changes, username):
    try:
        AuditEvent.objects.create(
            model=key,
            object_id=str(instance.pk),
            label=_label(instance),
            action=action,
            changes=changes,
            username=username,
        )
    except Exception:  # noqa: BLE001
        # Das Protokoll darf einen Speichervorgang niemals scheitern lassen.
        logger.exception("Änderungsprotokoll konnte nicht geschrieben werden")


class AuditUserMiddleware:
    """Hinterlegt den angemeldeten Benutzer für die Signale."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_current_user(getattr(request, "user", None))
        try:
            return self.get_response(request)
        finally:
            reset_current_user(token)
