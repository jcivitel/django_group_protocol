# Generated by Django 5.1.4 on 2024-12-09 12:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("django_grp_backend", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="resident",
            name="picture",
            field=models.ImageField(blank=True, null=True, upload_to=""),
        ),
    ]