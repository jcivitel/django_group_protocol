# Generated by Django 5.1.4 on 2024-12-09 15:46

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_backend", "0004_alter_protocol_date_added_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="resident",
            name="moved_out_since",
            field=models.DateField(blank=True, default=None, null=True),
        ),
    ]