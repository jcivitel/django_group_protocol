"""Legt die Vorlage für die Teambesprechung an.

Die Teambesprechung ist kein Gruppenabend: dort sitzt das Team, nicht die
Gruppe. Deshalb ein eigener Protokolltyp und keine Variante des
Gruppenabends - die Anwesenheit meint hier Mitarbeitende, und die
Tagesordnung dreht sich um Dienstplan, Absprachen und Fälle statt um den
Verlauf eines Abends.

Aufbau wie in 0022: vorhandene Vorlagen gleichen Namens bleiben unberührt,
damit eine angepasste Fassung eine erneute Migration übersteht.
"""

from django.db import migrations

TEMPLATE = {
    "name": "Teambesprechung",
    "description": "Regelmäßige Sitzung des Teams",
    "position": 5,
    "items": [
        {
            "name": "Offene Punkte vom letzten Mal",
            "kind": "text",
            "hint": "Was ist liegen geblieben?",
        },
        {
            "name": "Organisatorisches",
            "kind": "text",
            "hint": "Dienstplan, Urlaub, Vertretungen, Absprachen im Haus",
        },
        {
            "name": "Gruppe und einzelne Bewohner",
            "kind": "text",
            "hint": "Fachlicher Austausch. Mit @ eine Person erwähnen.",
        },
        {
            "name": "Beschlüsse",
            "kind": "table",
            "columns": ["Beschluss", "Verantwortung", "Frist"],
            "rows": 3,
        },
        {
            "name": "Nächste Besprechung",
            "kind": "text",
            "hint": "Wann, und was steht dann an?",
        },
    ],
}


def create_template(apps, schema_editor):
    ProtocolTemplate = apps.get_model("django_grp_backend", "ProtocolTemplate")
    ProtocolTemplateItem = apps.get_model("django_grp_backend", "ProtocolTemplateItem")

    if ProtocolTemplate.objects.filter(
        name=TEMPLATE["name"], group__isnull=True
    ).exists():
        return

    template = ProtocolTemplate.objects.create(
        name=TEMPLATE["name"],
        description=TEMPLATE["description"],
        position=TEMPLATE["position"],
        is_active=True,
    )
    for position, item in enumerate(TEMPLATE["items"], start=1):
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


def remove_template(apps, schema_editor):
    ProtocolTemplate = apps.get_model("django_grp_backend", "ProtocolTemplate")
    # Nur löschen, solange kein Protokoll daran hängt.
    ProtocolTemplate.objects.filter(
        name=TEMPLATE["name"], group__isnull=True, protocols__isnull=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_backend", "0023_resident_contact"),
    ]

    operations = [
        migrations.RunPython(create_template, remove_template),
    ]
