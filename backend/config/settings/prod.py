import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

DEBUG = False

_secret_key = os.environ.get("DJANGO_SECRET_KEY", "")
if (
    not _secret_key
    or _secret_key in {"dev-insecure-change-me", "cambiami-in-produzione"}
    or len(_secret_key) < 50
):
    raise ImproperlyConfigured(
        "In produzione imposta DJANGO_SECRET_KEY con un valore casuale di almeno 50 caratteri."
    )
SECRET_KEY = _secret_key

# In produzione gli host e le origini vanno definiti esplicitamente via env.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "1") == "1"
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = (
    os.environ.get("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "1") == "1"
)
SECURE_HSTS_PRELOAD = os.environ.get("DJANGO_SECURE_HSTS_PRELOAD", "1") == "1"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# UPPilot incorpora anteprime documento same-origin in iframe. Manteniamo
# SAMEORIGIN e silenziamo solo il warning Django relativo a DENY.
SILENCED_SYSTEM_CHECKS = ["security.W019"]
