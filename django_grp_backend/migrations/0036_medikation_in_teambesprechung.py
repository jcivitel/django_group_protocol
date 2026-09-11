"""
Der Medikationsplan gehört in jede Teambesprechung.

Bisher stand die Medikation nur in der Bewohnerakte. Wer dort nicht
nachsieht, erfährt von einer geänderten Verordnung im Zweifel gar nicht –
und genau darüber muss ein Team reden, weil die Gabe im Schichtdienst an
wechselnden Leuten hängt.

Der Baustein ist kein Freitext. Er schreibt beim Anlegen des Protokolls den
Plan der Gruppe ab und friert ihn ein: ein Protokoll ist ein Nachweis, und
im Protokoll vom März darf nicht die Lage vom September stehen.

Er steht bewusst vor „Gruppe und einzelne Bewohner": erst sieht das Team,
was gegeben wird, dann redet es darüber.
"""

from django.db import migrations

NAME = "Medikation"
HINWEIS = (
    "Was heute gilt, beim Anlegen dieses Protokolls abgeschrieben. "
    "Änderungen gehören in die Bewohnerakte."
)


def einfuegen(apps, schema_editor):
    ProtocolTemplate = apps.get_model("django_grp_backend", "ProtocolTemplate")
    ProtocolTemplateItem = apps.get_model(
        "django_grp_backend", "ProtocolTemplateItem"
    )

    for vorlage in ProtocolTemplate.objects.filter(name="Teambesprechung"):
        if vorlage.items.filter(kind="medication").exists():
            continue

        # Vor "Gruppe und einzelne Bewohner", sonst ans Ende. Eine angepasste
        # Vorlage soll nicht umsortiert werden, nur weil ein Punkt dazukommt.
        anker = vorlage.items.filter(
            name__startswith="Gruppe und einzelne"
        ).first()
        if anker is None:
            letzte = vorlage.items.order_by("-position").first()
            platz = (letzte.position + 1) if letzte else 0
        else:
            platz = anker.position
            for spaeter in vorlage.items.filter(position__gte=platz):
                spaeter.position += 1
                spaeter.save(update_fields=["position"])

        ProtocolTemplateItem.objects.create(
            template=vorlage,
            name=NAME,
            kind="medication",
            hint=HINWEIS,
            position=platz,
        )


def entfernen(apps, schema_editor):
    ProtocolTemplateItem = apps.get_model(
        "django_grp_backend", "ProtocolTemplateItem"
    )
    ProtocolTemplateItem.objects.filter(
        template__name="Teambesprechung", kind="medication"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_backend", "0035_aufgaben_erledigen"),
    ]

    operations = [migrations.RunPython(einfuegen, entfernen)]
