from django.urls import path

from .views import (
    AnnullaAnalisiView,
    ApprofondisciView,
    AvviaAnalisiView,
    AvviaRicercaView,
    BozzaView,
    EsportaDocxView,
    FattoProcessualeUpdateView,
    MatriceLavoroView,
    RicercaManualeView,
    RichiestaUpdateView,
    RichiesteListView,
    SpuntiListView,
)

urlpatterns = [
    path("lavori/<int:lavoro_id>/analizza/", AvviaAnalisiView.as_view(), name="analizza"),
    path("lavori/<int:lavoro_id>/annulla/", AnnullaAnalisiView.as_view(), name="annulla"),
    path("lavori/<int:lavoro_id>/approfondisci/", ApprofondisciView.as_view(), name="approfondisci"),
    path("lavori/<int:lavoro_id>/richieste/", RichiesteListView.as_view(), name="richieste"),
    path("lavori/<int:lavoro_id>/matrice/", MatriceLavoroView.as_view(), name="matrice"),
    path("richieste/<int:pk>/", RichiestaUpdateView.as_view(), name="richiesta-update"),
    path("matrice/<int:pk>/", FattoProcessualeUpdateView.as_view(), name="matrice-update"),
    path("lavori/<int:lavoro_id>/bozza/", BozzaView.as_view(), name="bozza"),
    path("lavori/<int:lavoro_id>/esporta/", EsportaDocxView.as_view(), name="esporta"),
    path("lavori/<int:lavoro_id>/ricerca/", AvviaRicercaView.as_view(), name="ricerca"),
    path("lavori/<int:lavoro_id>/ricerca/manuale/", RicercaManualeView.as_view(), name="ricerca-manuale"),
    path("lavori/<int:lavoro_id>/spunti/", SpuntiListView.as_view(), name="spunti"),
]
