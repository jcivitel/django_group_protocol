"""
Medikation vor „Gruppe und einzelne Bewohner", nicht hinter die Beschlüsse.

0036 wollte den Baustein genau dorthin setzen und landete am Ende. Der
Grund war ein Fehler in dieser Migration, nicht in der Absicht: die Zeilen
wurden verschoben, während über dasselbe QuerySet gelaufen wurde. Django
wertet es faul aus, das Verschieben ändert die Sortierung, und ein Teil der
Zeilen wurde doppelt oder gar nicht angefasst.

Hier wird die Liste deshalb erst geholt (`list(...)`) und dann verändert.

Die Reihenfolge ist keine Kosmetik: erst sieht das Team, was gegeben wird,
dann redet es über die Kinder. Andersherum ist die Medikation der Anhang,
den man liest, wenn die Zeit reicht.
"""

from django.db import migrations

VORLAGE = "Teambesprechung"
DAVOR = "Gruppe und einzelne"


def sortieren(apps, schema_editor):
    ProtocolTemplate = apps.get_model("django_grp_backend", "ProtocolTemplate")

    for vorlage in ProtocolTemplate.objects.filter(name=VORLAGE):
        punkte = list(vorlage.items.order_by("position", "id"))
        medikation = next((p for p in punkte if p.kind == "medication"), None)
        if medikation is None:
            continue

        uebrige = [p for p in punkte if p.id != medikation.id]
        ziel = next(
            (i for i, p in enumerate(uebrige) if p.name.startswith(DAVOR)),
            len(uebrige),
        )
        neu = uebrige[:ziel] + [medikation] + uebrige[ziel:]

        # Erst alles zählen, dann schreiben. Keine Abfrage mehr, während
        # sich die Sortierung unter den Füßen ändert.
        for platz, punkt in enumerate(neu):
            if punkt.position != platz:
                punkt.position = platz
                punkt.save(update_fields=["position"])


def zurueck(apps, schema_editor):
    """
    Kein Weg zurück.

    Die alte Reihenfolge war ein Versehen, und eine Migration, die ein
    Versehen wiederherstellt, hilft niemandem.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_backend", "0038_tagesprotokoll"),
    ]

    operations = [migrations.RunPython(sortieren, zurueck)]
