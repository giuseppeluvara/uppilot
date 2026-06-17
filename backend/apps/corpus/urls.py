from django.urls import path

from .views import CercaView, CorpusListView, IngestView

urlpatterns = [
    path("corpus/", CorpusListView.as_view(), name="corpus-list"),
    path("corpus/ingest/", IngestView.as_view(), name="corpus-ingest"),
    path("corpus/cerca/", CercaView.as_view(), name="corpus-cerca"),
]
