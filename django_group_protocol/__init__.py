# Celery muss beim Start von Django geladen werden, damit @shared_task die
# Anwendung findet.
from .celery import app as celery_app

__all__ = ("celery_app",)
