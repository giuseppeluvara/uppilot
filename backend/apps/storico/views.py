from rest_framework import generics

from apps.casi.models import Lavoro
from apps.casi.serializers import LavoroSerializer


class StoricoListView(generics.ListAPIView):
    """Elenco di tutti i lavori dell'utente per la sezione Archivio/Storico (§159)."""

    serializer_class = LavoroSerializer

    def get_queryset(self):
        return Lavoro.objects.filter(utente=self.request.user)
