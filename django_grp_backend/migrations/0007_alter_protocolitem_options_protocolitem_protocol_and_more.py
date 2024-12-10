# Generated by Django 5.1.4 on 2024-12-10 10:38

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_backend", "0006_alter_resident_picture"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="protocolitem",
            options={"ordering": ["position"]},
        ),
        migrations.AddField(
            model_name="protocolitem",
            name="protocol",
            field=models.ForeignKey(
                default=1,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="items",
                to="django_grp_backend.protocol",
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="protocolitem",
            name="position",
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="protocolitem",
            name="value",
            field=models.TextField(blank=True, null=True),
        ),
    ]