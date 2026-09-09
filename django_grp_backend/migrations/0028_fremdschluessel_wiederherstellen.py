"""
Fremdschlüssel wieder in der Datenbank verankern.

Die Beziehungen liefen mit `db_constraint=False`, weil ein Windows-Bind-Mount
als MariaDB-Datenverzeichnis kein "ADD FOREIGN KEY" zuließ. Das
docker-compose nutzt inzwischen ein Named Volume; der Workaround war überholt
und kostete nur noch referenzielle Integrität.

Voraussetzung ist 0027: der Bestand muss frei von verwaisten Zeilen sein,
sonst bricht das ALTER TABLE hier ab.

Außerdem: Group.color bekommt eine sichtbare Vorgabe. Weiß auf hellem Grund
hieß für eine Gruppe ohne gewählte Farbe: gar keine Kennfarbe.
"""


import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('django_grp_backend', '0027_verwaiste_zeilen_entfernen'),
    ]

    operations = [
        migrations.AlterField(
            model_name='group',
            name='color',
            field=models.CharField(default='#abc270', max_length=9),
        ),
        migrations.AlterField(
            model_name='protocol',
            name='template',
            field=models.ForeignKey(blank=True, help_text='Protokolltyp, aus dem die Tagesordnung erzeugt wurde', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='protocols', to='django_grp_backend.protocoltemplate', verbose_name='Vorlage'),
        ),
        migrations.AlterField(
            model_name='protocolattendance',
            name='protocol',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attendances', to='django_grp_backend.protocol'),
        ),
        migrations.AlterField(
            model_name='protocolattendance',
            name='resident',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='django_grp_backend.resident'),
        ),
        migrations.AlterField(
            model_name='protocolobservation',
            name='protocol',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='observations', to='django_grp_backend.protocol'),
        ),
        migrations.AlterField(
            model_name='protocolobservation',
            name='resident',
            field=models.ForeignKey(blank=True, help_text='Leer lassen für die Gruppe insgesamt', null=True, on_delete=django.db.models.deletion.CASCADE, to='django_grp_backend.resident', verbose_name='Bewohner'),
        ),
        migrations.AlterField(
            model_name='protocoltemplate',
            name='group',
            field=models.ForeignKey(blank=True, help_text='Leer lassen, damit die Vorlage für alle Gruppen gilt', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='protocol_templates', to='django_grp_backend.group', verbose_name='Gruppe'),
        ),
        migrations.AlterField(
            model_name='protocoltemplateitem',
            name='template',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='django_grp_backend.protocoltemplate'),
        ),
        migrations.AlterField(
            model_name='residentcontact',
            name='resident',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='contacts', to='django_grp_backend.resident', verbose_name='Bewohner:in'),
        ),
    ]
