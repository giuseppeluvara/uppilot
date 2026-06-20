import os
import zipfile
from io import BytesIO

from django.http import HttpResponse
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import Documento, Lavoro


def _estrai_testo_modello(uploaded) -> str:
    """Estrazione inline del testo del modello di redazione (PDF / DOCX / testo)."""
    nome = uploaded.name.lower()
    data = uploaded.read()
    if nome.endswith(".pdf"):
        import fitz

        with fitz.open(stream=data, filetype="pdf") as doc:
            return "\n".join(p.get_text("text") for p in doc).strip()
    if nome.endswith(".docx"):
        from docx import Document as Docx

        return "\n".join(p.text for p in Docx(BytesIO(data)).paragraphs).strip()
    return data.decode("utf-8", errors="ignore").strip()
from .serializers import (
    DocumentoSerializer,
    DocumentoUploadSerializer,
    LavoroSerializer,
)
from .tasks import estrai_testo_documento, pseudonimizza_documento


class LavoroViewSet(viewsets.ModelViewSet):
    """CRUD dei Lavori dell'utente autenticato (storicizzati)."""

    serializer_class = LavoroSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

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

    @action(detail=True, methods=["get"], url_path="documenti-zip")
    def documenti_zip(self, request, pk=None):
        """Scarica in un unico .zip tutti i documenti caricati del lavoro."""
        lavoro = self.get_object()
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            usati: set[str] = set()
            for doc in Documento.objects.filter(sezione__lavoro=lavoro).select_related("sezione"):
                if not doc.file:
                    continue
                nome = os.path.basename(doc.file.name)
                # Evita collisioni di nome (cartella per sezione + id se serve).
                arc = f"{doc.sezione.tipo}/{nome}"
                if arc in usati:
                    arc = f"{doc.sezione.tipo}/{doc.id}_{nome}"
                usati.add(arc)
                with doc.file.open("rb") as fh:
                    zf.writestr(arc, fh.read())
        resp = HttpResponse(buffer.getvalue(), content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="documenti_lavoro_{lavoro.id}.zip"'
        return resp

    @action(detail=True, methods=["post"], url_path="modello")
    def modello(self, request, pk=None):
        """Imposta (o cancella) il modello di redazione: file (PDF/DOCX/txt) o testo."""
        lavoro = self.get_object()
        upload = request.FILES.get("file")
        if upload is not None:
            try:
                testo = _estrai_testo_modello(upload)
            except Exception:  # noqa: BLE001
                return Response(
                    {"detail": "Impossibile leggere il file. Usa PDF, DOCX o testo."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            testo = (request.data.get("testo") or "").strip()
        lavoro.modello_testo = testo
        lavoro.save(update_fields=["modello_testo", "updated_at"])
        return Response(LavoroSerializer(lavoro).data)


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
