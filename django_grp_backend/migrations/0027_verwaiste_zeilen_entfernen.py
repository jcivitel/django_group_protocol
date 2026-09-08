"""
Verwaiste Zeilen entfernen, bevor die Fremdschlüssel wieder greifen.

Die betroffenen Beziehungen liefen jahrelang mit `db_constraint=False`. Django
hat sie geprüft, die Datenbank nicht — und alles, was an Django vorbei ging
(ein Löschen im Datenbankwerkzeug, ein Import, ein `.delete()` auf einem
QuerySet, das die Rückbeziehung nicht kannte), konnte Zeilen hinterlassen, die
auf nichts mehr zeigen.

Die nächste Migration setzt die Constraints. Ohne diesen Schritt bricht sie
auf genau solchen Beständen ab — mitten im Ausrollen, mit einer Meldung über
einen Fremdschlüssel, die niemand erwartet hat.

Was hier gelöscht wird, ist bereits unerreichbar: eine Teilnahme ohne
Bewohner erscheint in keiner Ansicht und in keinem PDF. Der Lauf schreibt
auf, was er entfernt hat.
"""

import logging

from django.db import migrations

logger = logging.getLogger("django_grp.migration")

# Modell, Feld, Zielmodell — genau die Beziehungen, die db_constraint=False
# getragen haben.
BEZIEHUNGEN = [
    ("Protocol", "template", "ProtocolTemplate"),
    ("ProtocolAttendance", "protocol", "Protocol"),
    ("ProtocolAttendance", "resident", "Resident"),
    ("ProtocolObservation", "protocol", "Protocol"),
    ("ProtocolObservation", "resident", "Resident"),
    ("ProtocolTemplate", "group", "Group"),
    ("ProtocolTemplateItem", "template", "ProtocolTemplate"),
    ("ResidentContact", "resident", "Resident"),
]


def aufraeumen(apps, schema_editor):
    for modellname, feld, zielname in BEZIEHUNGEN:
        modell = apps.get_model("django_grp_backend", modellname)
        ziel = apps.get_model("django_grp_backend", zielname)

        vorhanden = set(ziel.objects.values_list("id", flat=True))
        spalte = f"{feld}_id"

        # Nur Zeilen, die auf eine Nummer zeigen, die es nicht mehr gibt.
        # NULL ist in Ordnung, wo das Feld optional ist.
        verwaist = [
            zeile_id
            for zeile_id, ziel_id in modell.objects.values_list("id", spalte)
            if ziel_id is not None and ziel_id not in vorhanden
        ]

        if verwaist:
            modell.objects.filter(id__in=verwaist).delete()
            logger.warning(
                "%s: %s verwaiste Zeilen ohne %s entfernt",
                modellname,
                len(verwaist),
                zielname,
            )


def zurueck(apps, schema_editor):
    """Gelöschtes lässt sich nicht wiederherstellen - der Rückweg tut nichts."""


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_backend", "0026_delete_userpermission"),
    ]

    operations = [
        migrations.RunPython(aufraeumen, zurueck),
    ]
