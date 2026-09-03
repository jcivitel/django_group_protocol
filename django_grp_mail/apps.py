from django.apps import AppConfig


class MailConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_grp_mail"
    verbose_name = "E-Mail"

    def ready(self):
        # Die Signale haengen die Benachrichtigungen an die Fachvorgaenge.
        from . import signals  # noqa: F401
