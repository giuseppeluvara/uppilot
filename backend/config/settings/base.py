"""Impostazioni comuni di UPPilot."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get(
    "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1"
).split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # terze parti
    "rest_framework",
    "corsheaders",
    # app UPPilot
    "apps.accounts",
    "apps.casi",
    "apps.analisi",
    "apps.storico",
    "apps.corpus",
    "apps.conoscenza",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "uppilot"),
        "USER": os.environ.get("POSTGRES_USER", "uppilot"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "uppilot"),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_USER_MODEL = "accounts.Utente"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# Celery
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.environ.get(
    "CELERY_RESULT_BACKEND", "redis://redis:6379/1"
)

# --- Configurazione servizi AI (consumata da apps/ai) ---
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
PRIVACY_FILTER_URL = os.environ.get("PRIVACY_FILTER_URL", "http://privacy-filter:8000")
LLM_BACKEND = os.environ.get("LLM_BACKEND", "ollama")
OCR_MODEL = os.environ.get("OCR_MODEL", "glm-ocr:latest")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3:8b")
# Embedding locale per il RAG (§83). nomic-embed-text -> 768 dimensioni.
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "768"))

# LLM commerciale (OPT-IN, §5): usato solo su richiesta esplicita, sempre su
# testo pseudonimizzato. Provider di riferimento Anthropic; modello più capace.
COMMERCIAL_LLM_PROVIDER = os.environ.get("COMMERCIAL_LLM_PROVIDER", "anthropic")
COMMERCIAL_LLM_API_KEY = os.environ.get("COMMERCIAL_LLM_API_KEY", "")
COMMERCIAL_LLM_MODEL = os.environ.get("COMMERCIAL_LLM_MODEL", "claude-opus-4-8")

# Cartella dei sample/template di output (§7). Se contiene `template.docx`,
# viene usato come base per l'export Word (intestazioni, stili, P.Q.M.).
SAMPLE_OUTPUT_DIR = BASE_DIR / "sample_output"

# Ricerca giuridica (§6): "stub" (default, nessuna ricerca esterna) | "web".
# La query esce SEMPRE pseudonimizzata (§134).
LEGAL_SEARCH_BACKEND = os.environ.get("LEGAL_SEARCH_BACKEND", "stub")

LANGUAGE_CODE = "it-it"
TIME_ZONE = "Europe/Rome"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Limite applicativo sugli upload. Evita che fascicoli o corpus enormi saturino
# worker/LLM/OCR prima di una gestione a chunk più avanzata.
UPPILOT_MAX_UPLOAD_BYTES = int(
    os.environ.get("UPPILOT_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024))
)

# Consente l'anteprima dei documenti in iframe same-origin (la SPA li incorpora
# dalla propria origine via proxy). Default Django = DENY, che bloccherebbe l'embed.
X_FRAME_OPTIONS = "SAMEORIGIN"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
