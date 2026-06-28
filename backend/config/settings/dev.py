from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Frontend Vite in dev
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://mac-mini.local:5173",
    "http://mac-mini-giuseppe-luvara.local:5173",
    "http://192.168.1.62:5173",
]
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS
