# Generated migration to allow null pdf_template in Group model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('django_grp_backend', '0019_rename_todo_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='group',
            name='pdf_template',
            field=models.FileField(blank=True, null=True, upload_to='docs/'),
        ),
    ]
