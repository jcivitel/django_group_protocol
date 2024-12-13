from django.apps import apps
from django.contrib import admin

# Register your models here.
for model in apps.get_app_config("django_grp_backend").models.values():
    admin.site.register(model)
