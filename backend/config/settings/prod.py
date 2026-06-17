from .base import *  # noqa: F401,F403

DEBUG = False

# In produzione gli host e le origini vanno definiti esplicitamente via env.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
