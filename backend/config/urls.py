from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthz(_request):
    """Endpoint di health-check usato dai container."""
    return JsonResponse({"status": "ok", "service": "uppilot-backend"})


urlpatterns = [
    path("healthz", healthz),
    path("admin/", admin.site.urls),
    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.casi.urls")),
    path("api/", include("apps.analisi.urls")),
    path("api/", include("apps.storico.urls")),
    path("api/", include("apps.corpus.urls")),
]

# In sviluppo Django serve i file caricati (per l'anteprima dei documenti).
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
