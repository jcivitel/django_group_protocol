"""Legt Standardvorlagen für Protokolltypen an.

Die Gliederungen folgen den Empfehlungen zur sozialen Gruppenarbeit
(Thema, Verlauf, Beobachtungen, Vereinbarungen) aus Phase 6 der Roadmap.
Sie gelten trägerweit (ohne Gruppe) und lassen sich in der Oberfläche
anpassen oder deaktivieren.
"""

from django.db import migrations

TEMPLATES = [
    {
        "name": "Gruppenabend",
        "description": "Regelmäßige Runde der Wohngruppe",
        "position": 1,
        "items": [
            {
                "name": "Thema und Anlass",
                "kind": "text",
                "hint": "Worum ging es heute?",
            },
            {
                "name": "Verlauf",
                "kind": "text",
                "hint": "Wie ist der Abend gelaufen? Mit @ Bewohner erwähnen.",
            },
            {
                "name": "Beobachtungen",
                "kind": "text",
                "hint": "Auffälligkeiten, Stimmung, Gruppendynamik",
            },
            {
                "name": "Vereinbarungen",
                "kind": "table",
                "columns": ["Vereinbarung", "Wer", "Bis wann"],
                "rows": 3,
            },
        ],
    },
    {
        "name": "Tagesgruppenangebot",
        "description": "Pädagogisches Angebot in der Tagesgruppe",
        "position": 2,
        "items": [
            {
                "name": "Angebot und Ziel",
                "kind": "text",
                "hint": "Was war geplant, welches Ziel stand dahinter?",
            },
            {"name": "Ablauf", "kind": "text", "hint": "Wie lief das Angebot?"},
            {
                "name": "Beteiligung",
                "kind": "table",
                "columns": ["Kind", "Beteiligung", "Beobachtung"],
                "rows": 4,
            },
            {
                "name": "Nächste Schritte",
                "kind": "table",
                "columns": ["Maßnahme", "Verantwortung", "Termin"],
                "rows": 3,
            },
        ],
    },
    {
        "name": "Projektgruppe",
        "description": "Zeitlich begrenztes Projekt mit fester Gruppe",
        "position": 3,
        "items": [
            {"name": "Projektstand", "kind": "text", "hint": "Wo stehen wir?"},
            {
                "name": "Ergebnisse dieser Sitzung",
                "kind": "text",
                "hint": "Was wurde erarbeitet oder entschieden?",
            },
            {
                "name": "Aufgabenverteilung",
                "kind": "table",
                "columns": ["Aufgabe", "Verantwortung", "Termin", "Status"],
                "rows": 4,
            },
            {
                "name": "Nächster Termin",
                "kind": "text",
                "hint": "Wann geht es weiter, was steht dann an?",
            },
        ],
    },
    {
        "name": "Fallbesprechung",
        "description": "Kollegiale Beratung zu einer einzelnen Person",
        "position": 4,
        "items": [
            {
                "name": "Anlass",
                "kind": "text",
                "hint": "Warum wird der Fall besprochen?",
            },
            {
                "name": "Sachstand",
                "kind": "text",
                "hint": "Bisheriger Verlauf und aktuelle Lage",
            },
            {
                "name": "Fachliche Einschätzung",
                "kind": "text",
                "hint": "Sicht des Teams",
            },
            {
                "name": "Beschlüsse",
                "kind": "table",
                "columns": ["Beschluss", "Verantwortung", "Frist"],
                "rows": 3,
            },
        ],
    },
]


def create_templates(apps, schema_editor):
    ProtocolTemplate = apps.get_model("django_grp_backend", "ProtocolTemplate")
    ProtocolTemplateItem = apps.get_model("django_grp_backend", "ProtocolTemplateItem")

    for entry in TEMPLATES:
        # Vorhandene Vorlagen gleichen Namens nicht überschreiben - der Träger
        # darf sie angepasst haben.
        if ProtocolTemplate.objects.filter(
            name=entry["name"], group__isnull=True
        ).exists():
            continue

        template = ProtocolTemplate.objects.create(
            name=entry["name"],
            description=entry["description"],
            position=entry["position"],
            is_active=True,
        )
        for position, item in enumerate(entry["items"], start=1):
            ProtocolTemplateItem.objects.create(
                template=template,
                name=item["name"],
                position=position,
                kind=item["kind"],
                hint=item.get("hint", ""),
                value=item.get("value", ""),
                columns=item.get("columns"),
                rows=item.get("rows", 3),
            )


def remove_templates(apps, schema_editor):
    ProtocolTemplate = apps.get_model("django_grp_backend", "ProtocolTemplate")
    names = [entry["name"] for entry in TEMPLATES]
    # Nur löschen, solange keine Protokolle daran hängen.
    ProtocolTemplate.objects.filter(
        name__in=names, group__isnull=True, protocols__isnull=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        (
            "django_grp_backend",
            "0021_alter_protocoltodo_options_protocol_topic_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(create_templates, remove_templates),
    ]
