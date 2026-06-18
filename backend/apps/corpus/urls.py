from django.urls import path

from .views import (
    CercaView,
    CorpusDocumentoView,
    CorpusListView,
    FrammentiView,
    FrammentoView,
    IngestView,
)

urlpatterns = [
    path("corpus/", CorpusListView.as_view(), name="corpus-list"),
    path("corpus/ingest/", IngestView.as_view(), name="corpus-ingest"),
    path("corpus/cerca/", CercaView.as_view(), name="corpus-cerca"),
    path("corpus/frammenti/<int:pk>/", FrammentoView.as_view(), name="corpus-frammento"),
    path("corpus/<int:pk>/", CorpusDocumentoView.as_view(), name="corpus-documento"),
    path("corpus/<int:pk>/frammenti/", FrammentiView.as_view(), name="corpus-frammenti"),
]
