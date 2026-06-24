from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path
import json
import urllib.request


def healthz(_request):
    """Endpoint di health-check usato dai container."""
    return JsonResponse({"status": "ok", "service": "uppilot-backend"})


def _check_http(name: str, url: str, *, model: str | None = None) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
        models = [m.get("name") or m.get("model") for m in payload.get("models", [])]
        ok = True if model is None else model in models or f"{model}:latest" in models
        return {"ok": ok, "detail": "ok" if ok else f"modello non trovato: {model}"}
    except Exception as exc:  # noqa: BLE001 - health check diagnostico
        return {"ok": False, "detail": f"{name} non raggiungibile: {exc}"}


def health_ai(_request):
    """Health operativo per UI/preflight: servizi necessari ai task locali."""
    checks: dict[str, dict] = {}
    try:
        connection.ensure_connection()
        checks["db"] = {"ok": True, "detail": "ok"}
    except Exception as exc:  # noqa: BLE001
        checks["db"] = {"ok": False, "detail": str(exc)}

    try:
        import redis

        redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2).ping()
        checks["redis"] = {"ok": True, "detail": "ok"}
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = {"ok": False, "detail": str(exc)}

    checks["privacy_filter"] = _check_http(
        "privacy-filter", f"{settings.PRIVACY_FILTER_URL.rstrip('/')}/healthz"
    )
    ollama_url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags"
    checks["ollama_llm"] = _check_http("ollama", ollama_url, model=settings.LLM_MODEL)
    checks["ollama_embedding"] = _check_http(
        "ollama", ollama_url, model=settings.EMBEDDING_MODEL
    )
    checks["ollama_ocr"] = _check_http("ollama", ollama_url, model=settings.OCR_MODEL)

    ok = all(c.get("ok") for c in checks.values())
    hint = ""
    if not checks["ollama_llm"]["ok"] or not checks["ollama_embedding"]["ok"]:
        hint = (
            "Ollama non raggiungibile dal container. Avvia sul Mac con "
            "OLLAMA_HOST=0.0.0.0:11434 ollama serve e verifica OLLAMA_BASE_URL="
            "http://host.docker.internal:11434."
        )
    return JsonResponse({"ok": ok, "checks": checks, "hint": hint})


urlpatterns = [
    path("healthz", healthz),
    path("api/health/ai/", health_ai),
    path("admin/", admin.site.urls),
    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.casi.urls")),
    path("api/", include("apps.analisi.urls")),
    path("api/", include("apps.storico.urls")),
    path("api/", include("apps.corpus.urls")),
    path("api/", include("apps.conoscenza.urls")),
]

# In sviluppo Django serve i file caricati (per l'anteprima dei documenti).
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
