"""
Celery-Anwendung.

Der Broker steht in CELERY_BROKER_URL (Vorgabe: der Redis-Container aus
docker-compose.yml). Faellt er aus, laeuft die Anwendung weiter: der
Mailversand faellt dann auf den direkten Weg zurueck, siehe
django_grp_mail/service.py.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_group_protocol.settings")

app = Celery("gruppenprotokoll")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
