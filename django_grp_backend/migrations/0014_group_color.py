# Generated by Django 5.1.4 on 2024-12-19 11:22

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_backend", "0013_group_pdf_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="group",
            name="color",
            field=models.CharField(default="#000000", max_length=9),
        ),
    ]