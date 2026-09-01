from django.apps import apps
from django.contrib import admin

# Alle Modelle dieser App im Admin verfuegbar machen.
for model in apps.get_app_config("django_grp_org").models.values():
    try:
        admin.site.register(model)
    except admin.sites.AlreadyRegistered:
        pass
