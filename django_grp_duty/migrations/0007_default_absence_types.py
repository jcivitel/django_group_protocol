"""Legt Abwesenheitsarten als Vorgabe an.

Ohne mindestens eine Abwesenheitsart ist „Abwesenheit beantragen" dauerhaft
ausgegraut — und zwar ohne dass irgendwo stünde, warum. Die Dienstplanung
wirkt kaputt, obwohl nur die Stammdaten fehlen.

Angelegt wurden sie bisher ausschließlich vom Kommandozeilen-Werkzeug
`seed_organisation`. Der Einrichtungsassistent, den in der Praxis alle
benutzen, legte Arbeitszeitmodelle und Dienstarten an — diese hier nicht.
Wer über die Oberfläche eingerichtet hat, stand danach vor einem toten Knopf.

Diese Migration holt es für bestehende Installationen nach; für neue erledigt
es der Assistent (django_grp_core/organisation_setup.py). Die Liste steht in
django_grp_org/defaults.py, damit beide dieselbe benutzen. Angelegt wird nur,
was fehlt — eine umbenannte Vorgabe kommt nicht als Dublette zurück.
"""

from django.db import migrations

from django_grp_org.defaults import ensure_absence_types


def seed(apps, schema_editor):
    AbsenceType = apps.get_model("django_grp_duty", "AbsenceType")
    Provider = apps.get_model("django_grp_org", "Provider")

    # Abwesenheitsarten hängen am Träger. Gibt es noch keinen, ist die
    # Installation frisch - dann legt sie der Einrichtungsassistent an.
    for provider in Provider.objects.all():
        ensure_absence_types(AbsenceType, provider)


def unseed(apps, schema_editor):
    """Nur löschen, was an keiner Abwesenheit hängt."""
    from django_grp_org.defaults import DEFAULT_ABSENCE_TYPES

    AbsenceType = apps.get_model("django_grp_duty", "AbsenceType")
    AbsenceType.objects.filter(
        name__in=[eintrag[0] for eintrag in DEFAULT_ABSENCE_TYPES],
        absences__isnull=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_duty", "0006_on_call_minutes"),
        ("django_grp_org", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
