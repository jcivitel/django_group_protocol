"""
FULLTEXT-Indizes fuer die Suche.

Django kennt fuer MariaDB keinen Volltextindex, also von Hand. Drei Stellen,
an denen im Alltag gesucht wird: der Inhalt eines Tagesordnungspunkts, der
Text eines Verlaufseintrags und das Thema eines Protokolls.

**Warum nicht Elasticsearch.** Ein Traeger mit zwei Gruppen schreibt
vielleicht sechshundert Protokolle im Jahr - nach zehn Jahren ein paar
Megabyte Text. Dafuer einen zweiten Dienst mit eigener Java-Laufzeit, eigenem
Abgleich, eigener Sicherung und eigenem Aktualisierungspfad zu betreiben,
waere ein Vielfaches an Betrieb fuer einen Bruchteil an Nutzen. Und ein
Index, der nach einem Absturz still veraltet, ist schlimmer als keine Suche.

**Was InnoDB dabei nicht kann.** Es gibt keine deutsche Wortstammbildung:
"Medikament" findet "Medikamentenplan" nicht von allein. Die Suche haengt
deshalb an jedes Wort einen Stern - siehe `django_grp_backend/suche.py`. Und
die Stoppwortliste ist englisch, "der" und "und" landen also im Index. Das
kostet Platz und keine Richtigkeit; eine eigene Liste lohnt erst, wenn der
Index spuerbar wird.

Die Mindestlaenge eines Worts ist `innodb_ft_min_token_size`, ab Werk drei.
Wer nach zwei Buchstaben sucht, findet nichts - das faengt die Suche vorher
ab, statt eine leere Liste zu zeigen.
"""

from django.db import migrations

INDIZES = [
    ("django_grp_backend_protocolitem", "ft_protocolitem_value", "value"),
    ("django_grp_backend_protocolobservation", "ft_observation_text", "text"),
    ("django_grp_backend_protocol", "ft_protocol_topic", "topic"),
]


def anlegen(apps, schema_editor):
    """
    Anlegen, und einen Fehlschlag nicht verschweigen.

    Auf einer Installation ohne InnoDB-Volltext (oder auf einem Dateisystem,
    das den Umbau nicht mitmacht) soll die Migration durchlaufen - die Suche
    faellt dann auf LIKE zurueck und ist langsamer, aber richtig. Was nicht
    ging, steht in der Ausgabe: eine Suche, die still im Schneckengang
    laeuft, sucht nach einem halben Jahr jemand stundenlang.
    """
    if schema_editor.connection.vendor != "mysql":
        return

    with schema_editor.connection.cursor() as cursor:
        for tabelle, name, spalte in INDIZES:
            try:
                cursor.execute(
                    f"CREATE FULLTEXT INDEX {name} ON {tabelle} ({spalte})"
                )
            except Exception as fehler:  # noqa: BLE001
                print(
                    f"  Volltextindex {name} nicht angelegt: {fehler}\n"
                    f"  Die Suche laeuft dann ueber LIKE - richtig, aber langsam."
                )


def entfernen(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return

    with schema_editor.connection.cursor() as cursor:
        for tabelle, name, _ in INDIZES:
            try:
                cursor.execute(f"DROP INDEX {name} ON {tabelle}")
            except Exception:  # noqa: BLE001
                pass


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_backend", "0033_bewohnerakte_module_3_bis_7"),
    ]

    operations = [migrations.RunPython(anlegen, entfernen)]
