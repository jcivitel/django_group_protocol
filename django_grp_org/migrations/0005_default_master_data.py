"""Legt Qualifikationen und Arbeitszeitmodelle als Vorgabe an.

Beides war nach der Installation leer. Wer eine Qualifikation an einer
Person eintragen will, musste sie erst selbst anlegen - und wer nicht weiss,
welche Bezeichnungen ueblich sind, laesst es. Die Fachkraftquote im
Dienstplan rechnet dann mit nichts.

Die Liste steht in django_grp_org/defaults.py, damit der
Einrichtungsassistent dieselbe benutzt. Angelegt wird nur, was fehlt.
"""

from django.db import migrations

from django_grp_org.defaults import ensure_qualifications, ensure_worktime_models


def seed(apps, schema_editor):
    Qualification = apps.get_model("django_grp_org", "Qualification")
    WorkTimeModel = apps.get_model("django_grp_org", "WorkTimeModel")
    Provider = apps.get_model("django_grp_org", "Provider")

    ensure_qualifications(Qualification)

    # Arbeitszeitmodelle haengen an einem Traeger. Gibt es noch keinen, ist
    # die Installation frisch - dann legt sie der Einrichtungsassistent an,
    # sobald der Traeger entsteht.
    for provider in Provider.objects.all():
        ensure_worktime_models(WorkTimeModel, provider)


def unseed(apps, schema_editor):
    """Nur loeschen, was niemand benutzt."""
    from django_grp_org.defaults import (
        DEFAULT_QUALIFICATIONS,
        DEFAULT_WORKTIME_MODELS,
    )

    Qualification = apps.get_model("django_grp_org", "Qualification")
    WorkTimeModel = apps.get_model("django_grp_org", "WorkTimeModel")

    Qualification.objects.filter(
        name__in=[name for name, _, _ in DEFAULT_QUALIFICATIONS],
        employeequalification__isnull=True,
    ).delete()
    WorkTimeModel.objects.filter(
        name__in=[name for name, *_ in DEFAULT_WORKTIME_MODELS],
        employee__isnull=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_org", "0004_merge_users_into_employees"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
