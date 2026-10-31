import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "online_voting.settings")

app = Celery("online_voting")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
