from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .models import Documento, Lavoro
from .serializers import (
    DocumentoSerializer,
    DocumentoUploadSerializer,
    LavoroSerializer,
)
from .tasks import estrai_testo_documento, pseudonimizza_documento


class LavoroViewSet(viewsets.ModelViewSet):
    """CRUD dei Lavori dell'utente autenticato (storicizzati)."""

    serializer_class = LavoroSerializer

    def get_queryset(self):
        return (
            Lavoro.objects.filter(utente=self.request.user)
            .prefetch_related("sezioni__documenti")
        )

    @action(detail=True, methods=["post"], url_path="accetta-tutti")
    def accetta_tutti(self, request, pk=None):
        """Accetta in blocco tutti i documenti pseudonimizzati del lavoro (§122)."""
        lavoro = self.get_object()
        documenti = Documento.objects.filter(
            sezione__lavoro=lavoro, pseudonimizzato=True
        )
        aggiornati = documenti.update(
            stato_accettazione=Documento.StatoAccettazione.ACCETTATO_SENZA_VERIFICA
        )
        return Response({"accettati": aggiornati})


class DocumentoViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Upload e consultazione dei documenti dell'utente."""

    parser_classes = [MultiPartParser, FormParser]

    def get_serializer_class(self):
        if self.action == "create":
            return DocumentoUploadSerializer
        return DocumentoSerializer

    def get_queryset(self):
        return Documento.objects.filter(
            sezione__lavoro__utente=self.request.user
        )

    def perform_create(self, serializer):
        documento = serializer.save()
        # Estrazione testo asincrona (§82): non blocca la risposta.
        estrai_testo_documento.delay(documento.id)

    def _imposta_accettazione(self, documento, nuovo_stato):
        # Vincolo §119: si può accettare solo dopo la pseudonimizzazione.
        if not documento.pseudonimizzato:
            return Response(
                {"detail": "Documento non ancora pseudonimizzato."},
                status=status.HTTP_409_CONFLICT,
            )
        documento.stato_accettazione = nuovo_stato
        documento.save(update_fields=["stato_accettazione"])
        return Response(DocumentoSerializer(documento).data)

    @action(detail=True, methods=["post"])
    def verifica(self, request, pk=None):
        """L'utente ha rivisto l'anonimizzazione e la conferma (§122)."""
        return self._imposta_accettazione(
            self.get_object(), Documento.StatoAccettazione.VERIFICATO
        )

    @action(detail=True, methods=["post"])
    def accetta(self, request, pk=None):
        """L'utente accetta senza verifica il singolo documento (§122)."""
        return self._imposta_accettazione(
            self.get_object(), Documento.StatoAccettazione.ACCETTATO_SENZA_VERIFICA
        )

    @action(detail=True, methods=["post"])
    def ripseudonimizza(self, request, pk=None):
        """Riprova l'anonimizzazione di un documento (resilienza)."""
        documento = self.get_object()
        pseudonimizza_documento.delay(documento.id)
        documento.stato_anonimizzazione = Documento.StatoAnonimizzazione.IN_CORSO
        documento.errore_anonimizzazione = ""
        documento.save(update_fields=["stato_anonimizzazione", "errore_anonimizzazione"])
        return Response(DocumentoSerializer(documento).data, status=status.HTTP_202_ACCEPTED)
