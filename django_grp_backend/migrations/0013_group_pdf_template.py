# Generated by Django 5.1.4 on 2024-12-18 15:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_backend", "0012_alter_resident_picture"),
    ]

    operations = [
        migrations.AddField(
            model_name="group",
            name="pdf_template",
            field=models.FileField(blank=True, upload_to="docs/"),
        ),
    ]
