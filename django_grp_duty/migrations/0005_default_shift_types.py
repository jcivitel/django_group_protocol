"""Legt Dienstarten als Vorgabe an.

Ohne mindestens eine Dienstart erzeugt ein Dienstplan gar keine Dienste: das
Raster bleibt leer, und die Dienstplanung wirkt kaputt, obwohl nur die
Stammdaten fehlen. Eine Oberflaeche zum Anlegen gab es bis hierher nicht.

Die Liste steht in django_grp_org/defaults.py, damit der
Einrichtungsassistent dieselbe benutzt. Angelegt wird nur, was fehlt.
"""

from django.db import migrations

from django_grp_org.defaults import ensure_shift_types


def seed(apps, schema_editor):
    ShiftType = apps.get_model("django_grp_duty", "ShiftType")
    Provider = apps.get_model("django_grp_org", "Provider")

    # Dienstarten haengen am Traeger. Gibt es noch keinen, ist die
    # Installation frisch - dann legt sie der Einrichtungsassistent an.
    for provider in Provider.objects.all():
        ensure_shift_types(ShiftType, provider)


def unseed(apps, schema_editor):
    """Nur loeschen, was in keinem Plan benutzt wird."""
    from django_grp_org.defaults import DEFAULT_SHIFT_TYPES

    ShiftType = apps.get_model("django_grp_duty", "ShiftType")
    ShiftType.objects.filter(
        short_code__in=[eintrag[0] for eintrag in DEFAULT_SHIFT_TYPES],
        shifts__isnull=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_duty", "0004_staffing_requirement"),
        ("django_grp_org", "0005_default_master_data"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
