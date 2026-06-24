from django.urls import path

from .views import (
    AnnullaCostruzioneView,
    ArcoView,
    CostruisciView,
    GrafoView,
    NodoView,
    StatoView,
)

urlpatterns = [
    path("grafo/", GrafoView.as_view(), name="grafo"),
    path("grafo/costruisci/", CostruisciView.as_view(), name="grafo-costruisci"),
    path("grafo/annulla/", AnnullaCostruzioneView.as_view(), name="grafo-annulla"),
    path("grafo/stato/", StatoView.as_view(), name="grafo-stato"),
    path("grafo/nodo/<int:pk>/", NodoView.as_view(), name="grafo-nodo"),
    path("grafo/arco/<int:pk>/", ArcoView.as_view(), name="grafo-arco"),
]
