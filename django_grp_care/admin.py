from django.apps import apps
from django.contrib import admin

for model in apps.get_app_config("django_grp_care").models.values():
    try:
        admin.site.register(model)
    except admin.sites.AlreadyRegistered:
        pass
