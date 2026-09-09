"""Stellt die Teambesprechung an den Anfang der Vorlagenliste.

Beim Anlegen eines Protokolls steht "Leeres Protokoll" als erste Kachel,
danach folgen die Vorlagen nach `position`. Die Teambesprechung stand dort
ganz hinten, obwohl sie neben dem Gruppenabend die haeufigste ist: die
Gruppe trifft sich woechentlich, das Team auch.

Nur die traegerweiten Standardvorlagen werden umsortiert, und nur die, die
noch auf ihrer urspruenglichen Position stehen. Wer die Reihenfolge selbst
angefasst oder eigene Vorlagen angelegt hat, behaelt sie - eine Migration,
die eine bewusste Entscheidung ueberschreibt, ist keine Verbesserung.
"""

from django.db import migrations

# Name -> (bisherige Position, neue Position)
UMSORTIEREN = {
    "Teambesprechung": (5, 1),
    "Gruppenabend": (1, 2),
    "Tagesgruppenangebot": (2, 3),
    "Projektgruppe": (3, 4),
    "Fallbesprechung": (4, 5),
}


def nach_vorn(apps, schema_editor):
    ProtocolTemplate = apps.get_model("django_grp_backend", "ProtocolTemplate")

    for name, (alt, neu) in UMSORTIEREN.items():
        ProtocolTemplate.objects.filter(
            name=name, group__isnull=True, position=alt
        ).update(position=neu)


def zurueck(apps, schema_editor):
    ProtocolTemplate = apps.get_model("django_grp_backend", "ProtocolTemplate")

    for name, (alt, neu) in UMSORTIEREN.items():
        ProtocolTemplate.objects.filter(
            name=name, group__isnull=True, position=neu
        ).update(position=alt)


class Migration(migrations.Migration):
    dependencies = [
        ("django_grp_backend", "0029_feste_sortierung"),
    ]

    operations = [
        migrations.RunPython(nach_vorn, zurueck),
    ]
