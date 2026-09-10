"""
Aus jeder heutigen Zugriffsstufe wird eine Rollenzuweisung.

Schritt 1 aus rollenkonzept.md. Die neuen Zeilen liegen daneben und steuern
zunaechst nichts – entschieden wird weiterhin nach `Employee.access_level`.
Der Sinn ist, dass nach dieser Migration jede Person mindestens eine
Zuweisung hat und die daraus abgeleitete Stufe mit der alten uebereinstimmt.

Die Abbildung:

    admin       -> Geschaeftsfuehrung auf Traegerebene
    specialist  -> Fachkraft in jedem Bereich, dessen Gruppe die Person sieht
    assistant   -> Ergaenzungskraft ebenso

Wer heute in keiner Gruppe ist, bekommt die Rolle traegerweit. Sonst waere
er nach dem Umschalten auf Rollen ausgesperrt – und ausgesperrt zu werden
ist das eine, was diese Migration nicht tun darf.

Bestehende Zeilen mit den alten Werten werden mitgezogen: `management` wird
Einrichtungsleitung, `youth_office` wird externe Lesekraft.
"""

from django.db import migrations

# Die alten Rollenwerte auf die neuen. `specialist`, `assistant` und
# `administration` heissen unveraendert.
UMBENANNT = {
    "management": "facility_lead",
    "youth_office": "external_reader",
}


def rollen_anlegen(apps, schema_editor):
    Employee = apps.get_model("django_grp_org", "Employee")
    Role = apps.get_model("django_grp_org", "Role")
    Department = apps.get_model("django_grp_org", "Department")
    Group = apps.get_model("django_grp_backend", "Group")

    for alt, neu in UMBENANNT.items():
        Role.objects.filter(role=alt).update(role=neu)

    for employee in Employee.objects.select_related("provider", "user"):
        if employee.provider_id is None:
            continue

        stufe = employee.access_level
        seit = employee.hired_on

        if stufe == "admin":
            Role.objects.get_or_create(
                employee=employee,
                role="executive",
                provider_id=employee.provider_id,
                site=None,
                facility=None,
                department=None,
                case_file=None,
                defaults={"valid_from": seit, "note": "aus der Zugriffsstufe"},
            )
            continue

        rolle = "assistant" if stufe == "assistant" else "specialist"

        # Ohne Konto gibt es keine Gruppen - dann traegerweit, damit
        # niemand ohne Zuweisung dasteht.
        gruppen_ids = []
        if employee.user_id:
            gruppen_ids = list(
                Group.objects.filter(
                    group_members__id=employee.user_id
                ).values_list("id", flat=True)
            )

        bereiche = list(
            Department.objects.filter(
                group_id__in=gruppen_ids,
                facility__site__provider_id=employee.provider_id,
            )
        ) if gruppen_ids else []

        if not bereiche:
            Role.objects.get_or_create(
                employee=employee,
                role=rolle,
                provider_id=employee.provider_id,
                site=None,
                facility=None,
                department=None,
                case_file=None,
                defaults={"valid_from": seit, "note": "aus der Zugriffsstufe"},
            )
            continue

        for bereich in bereiche:
            Role.objects.get_or_create(
                employee=employee,
                role=rolle,
                provider_id=employee.provider_id,
                department=bereich,
                case_file=None,
                defaults={
                    "valid_from": seit,
                    "facility_id": bereich.facility_id,
                    "site_id": bereich.facility.site_id,
                    "note": "aus der Zugriffsstufe",
                },
            )


def zurueck(apps, schema_editor):
    """
    Nur die Zeilen zuruecknehmen, die diese Migration angelegt hat.

    Von Hand gepflegte Zuweisungen bleiben stehen – eine Ruecknahme, die
    fremde Daten mitnimmt, ist keine.
    """
    Role = apps.get_model("django_grp_org", "Role")
    Role.objects.filter(note="aus der Zugriffsstufe").delete()
    for alt, neu in UMBENANNT.items():
        Role.objects.filter(role=neu).update(role=alt)


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_org", "0011_rolle_mit_geltungsbereich"),
        ("django_grp_backend", "0033_bewohnerakte_module_3_bis_7"),
    ]

    operations = [migrations.RunPython(rollen_anlegen, zurueck)]
