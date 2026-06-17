"""Impostazioni per i test.

Usa Postgres (servizio `db`): il RAG richiede pgvector, non disponibile su sqlite.
I test girano nel container backend, dove il DB è raggiungibile; pytest-django crea
e distrugge un database di test dedicato.
"""
import os
import tempfile

from .base import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "uppilot"),
        "USER": os.environ.get("POSTGRES_USER", "uppilot"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "uppilot"),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "TEST": {"NAME": "test_uppilot"},
    }
}

# I task Celery girano in modo sincrono nei test (nessun broker necessario).
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

MEDIA_ROOT = tempfile.mkdtemp(prefix="uppilot-test-media-")
