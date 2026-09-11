"""
Die Tagesprotokoll-Vorlage, und sie steht an erster Stelle.

Was bisher fehlte: der Alltag. Gruppenabend, Teambesprechung und
Fallbesprechung sind Termine – das Tagesprotokoll ist die Schicht selbst.
Es wird am häufigsten geschrieben und stand als einziges nicht zur Auswahl,
also entstand es jedes Mal als leeres Protokoll von Hand.

Reihenfolge: Tagesprotokoll, dann Teambesprechung, dann der Rest wie
gehabt. Die Teambesprechung wurde in 0030 nach vorn geholt, weil sie die
häufigste war – das Tagesprotokoll ist es noch mehr.

Der Aufbau folgt dem Dienst und nicht der Verwaltung: erst die Übergabe,
dann was am Tag war, dann was für die nächste Schicht offen bleibt. Die
Medikation steht als eigener Baustein darin, aus demselben Grund wie in der
Teambesprechung: die Gabe hängt im Schichtdienst an wechselnden Leuten.

Wie in 0022 und 0024: eine vorhandene Vorlage gleichen Namens bleibt
unberührt, damit eine angepasste Fassung eine erneute Migration übersteht.
"""

from django.db import migrations

TEMPLATE = {
    "name": "Tagesprotokoll",
    "description": "Was in dieser Schicht war",
    "position": 0,
    "items": [
        {
            "name": "Übergabe",
            "kind": "text",
            "hint": "Was die vorige Schicht mitgegeben hat",
        },
        {
            "name": "Anwesenheit und Abwesenheit",
            "kind": "text",
            "hint": "Wer war da, wer nicht, und warum",
        },
        {
            "name": "Medikation",
            "kind": "medication",
            "hint": (
                "Was heute gilt, beim Anlegen dieses Protokolls "
                "abgeschrieben. Änderungen gehören in die Bewohnerakte."
            ),
        },
        {
            "name": "Verlauf des Tages",
            "kind": "text",
            "hint": "Schule, Termine, Mahlzeiten, Freizeit. Mit @ eine Person erwähnen.",
        },
        {
            "name": "Besonderheiten",
            "kind": "text",
            "hint": (
                "Konflikte, Auffälligkeiten, Gespräche. Meldepflichtiges "
                "gehört zusätzlich unter Vorkommnisse."
            ),
        },
        {
            "name": "Offen für die nächste Schicht",
            "kind": "table",
            "columns": ["Was", "Wer", "Bis wann"],
            "rows": 3,
        },
    ],
}

# Alles rückt um eins, damit das Tagesprotokoll auf 0 passt. Nur die
# trägerweiten Standardvorlagen, und nur die auf ihrer Position aus 0030.
NACHRUECKEN = {
    "Teambesprechung": (0, 1),
    "Gruppenabend": (2, 2),
    "Tagesgruppenangebot": (3, 3),
    "Projektgruppe": (4, 4),
    "Fallbesprechung": (5, 5),
}


def anlegen(apps, schema_editor):
    ProtocolTemplate = apps.get_model("django_grp_backend", "ProtocolTemplate")
    ProtocolTemplateItem = apps.get_model(
        "django_grp_backend", "ProtocolTemplateItem"
    )

    for name, (alt, neu) in NACHRUECKEN.items():
        if alt != neu:
            ProtocolTemplate.objects.filter(
                name=name, group__isnull=True, position=alt
            ).update(position=neu)

    if ProtocolTemplate.objects.filter(
        name=TEMPLATE["name"], group__isnull=True
    ).exists():
        return

    vorlage = ProtocolTemplate.objects.create(
        name=TEMPLATE["name"],
        description=TEMPLATE["description"],
        position=TEMPLATE["position"],
        is_active=True,
    )
    for platz, punkt in enumerate(TEMPLATE["items"]):
        felder = {
            "template": vorlage,
            "name": punkt["name"],
            "kind": punkt["kind"],
            "hint": punkt.get("hint", ""),
            "columns": punkt.get("columns"),
            "position": platz,
        }
        # `rows` hat einen Standardwert und darf nicht null sein. Nur bei
        # einer Tabelle ueberhaupt mitschicken.
        if punkt.get("rows") is not None:
            felder["rows"] = punkt["rows"]
        ProtocolTemplateItem.objects.create(**felder)


def entfernen(apps, schema_editor):
    ProtocolTemplate = apps.get_model("django_grp_backend", "ProtocolTemplate")
    ProtocolTemplate.objects.filter(
        name=TEMPLATE["name"], group__isnull=True
    ).delete()

    for name, (alt, neu) in NACHRUECKEN.items():
        if alt != neu:
            ProtocolTemplate.objects.filter(
                name=name, group__isnull=True, position=neu
            ).update(position=alt)


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_backend", "0037_medikation_als_art"),
    ]

    operations = [migrations.RunPython(anlegen, entfernen)]
