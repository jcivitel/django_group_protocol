"""
Tagesprotokoll und Teambesprechung standen beide auf Position 0.

0038 wollte die Teambesprechung von 0 auf 1 schieben und danach das
Tagesprotokoll auf 0 anlegen. Geschoben wurde nicht: 0030 hatte die
Teambesprechung bereits nach vorn geholt, und die Annahme in 0038 traf ihre
damalige Position nicht. Danach lagen zwei Vorlagen auf derselben Stelle.

Sichtbar falsch war das bisher nicht, weil `Meta.ordering` bei gleicher
Position nach Namen sortiert und "Tagesprotokoll" vor "Teambesprechung"
liegt. Genau das ist die Falle: die gewuenschte Reihenfolge haengt am
Anfangsbuchstaben. Wer eine der beiden Vorlagen umbenennt, dreht sie um, und
niemand verbindet das eine mit dem anderen.

Diese Migration schreibt die Reihenfolge hin, statt sie zu erben. Sie greift
nur, solange beide tatsaechlich auf 0 stehen - wer die Reihenfolge selbst
angefasst hat, behaelt sie.
"""

from django.db import migrations

ERSTE = "Tagesprotokoll"
ZWEITE = "Teambesprechung"


def _traegerweit(ProtocolTemplate, name):
    return ProtocolTemplate.objects.filter(name=name, group__isnull=True)


def entwirren(apps, schema_editor):
    ProtocolTemplate = apps.get_model("django_grp_backend", "ProtocolTemplate")

    erste = _traegerweit(ProtocolTemplate, ERSTE).first()
    zweite = _traegerweit(ProtocolTemplate, ZWEITE).first()
    if not erste or not zweite:
        return
    if erste.position != 0 or zweite.position != 0:
        return

    # Position 1 ist frei: 0038 hatte sie fuer genau diesen Fall vorgesehen,
    # und die uebrigen Vorlagen liegen seit 0030 auf 2 bis 5.
    zweite.position = 1
    zweite.save(update_fields=["position"])


def zurueck(apps, schema_editor):
    ProtocolTemplate = apps.get_model("django_grp_backend", "ProtocolTemplate")

    zweite = _traegerweit(ProtocolTemplate, ZWEITE).filter(position=1).first()
    if zweite:
        zweite.position = 0
        zweite.save(update_fields=["position"])


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_backend", "0040_druckbereich"),
    ]

    operations = [
        migrations.RunPython(entwirren, zurueck),
    ]
