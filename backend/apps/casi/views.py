import os
import zipfile
from io import BytesIO

from django.conf import settings
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

_MODELLO_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")


def _valida_upload_modello(uploaded):
    if uploaded.size > settings.UPPILOT_MAX_UPLOAD_BYTES:
        return Response(
            {
                "detail": (
                    "File troppo grande. Limite: "
                    f"{settings.UPPILOT_MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not uploaded.name.lower().endswith(_MODELLO_EXTENSIONS):
        return Response(
            {"detail": "Tipo di file non supportato. Usa PDF, DOCX o testo."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None


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
            if resp := _valida_upload_modello(upload):
                return resp
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

    @action(detail=True, methods=["post"], url_path="estrai-modello")
    def estrai_modello(self, request, pk=None):
        """Estrae il testo da un file SENZA salvarlo: l'operatore lo rivede e poi salva."""
        self.get_object()  # verifica proprietà del lavoro
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Nessun file."}, status=status.HTTP_400_BAD_REQUEST)
        if resp := _valida_upload_modello(upload):
            return resp
        try:
            testo = _estrai_testo_modello(upload)
        except Exception:  # noqa: BLE001
            return Response(
                {"detail": "Impossibile leggere il file. Usa PDF, DOCX o testo."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"testo": testo})


class DocumentoViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Upload e consultazione dei documenti dell'utente."""

    parser_classes = [JSONParser, MultiPartParser, FormParser]

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

    @action(detail=True, methods=["patch"], url_path="privacy")
    def privacy(self, request, pk=None):
        """Correzione manuale del testo pseudonimizzato e della mappa entità."""
        documento = self.get_object()
        testo = request.data.get("testo_pseudonimizzato")
        mappa = request.data.get("mappa_entita")
        campi: list[str] = []

        if testo is not None:
            documento.testo_pseudonimizzato = str(testo)
            documento.pseudonimizzato = bool(str(testo).strip())
            campi.extend(["testo_pseudonimizzato", "pseudonimizzato"])
        if mappa is not None:
            if not isinstance(mappa, dict):
                return Response(
                    {"detail": "mappa_entita deve essere un oggetto chiave/valore."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            documento.mappa_entita = {str(k): str(v) for k, v in mappa.items()}
            campi.append("mappa_entita")

        if campi:
            # Ogni modifica manuale richiede nuova conferma: evita che un documento
            # già accettato resti utilizzabile dopo una correzione non revisionata.
            documento.stato_accettazione = Documento.StatoAccettazione.DA_VERIFICARE
            if "stato_accettazione" not in campi:
                campi.append("stato_accettazione")
            documento.save(update_fields=campi)

            lavoro = documento.sezione.lavoro
            registro = dict(lavoro.mappa_entita or {})
            registro.update(documento.mappa_entita or {})
            lavoro.mappa_entita = registro
            lavoro.save(update_fields=["mappa_entita", "updated_at"])

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
