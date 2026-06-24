from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from ai.factory import get_embedding_backend

from .models import DocumentoCorpus, FrammentoCorpus
from .serializers import DocumentoCorpusSerializer
from .services import cerca
from .tasks import indicizza_documento_task


_CORPUS_FILE_EXTENSIONS = (".pdf", ".txt", ".md")


def _documenti_visibili(user):
    qs = DocumentoCorpus.objects.all()
    if user.is_staff:
        return qs
    return qs.filter(Q(creato_da__isnull=True) | Q(creato_da=user))


def _documenti_eliminabili(user):
    qs = DocumentoCorpus.objects.all()
    if user.is_staff:
        return qs
    return qs.filter(creato_da=user)


def _valida_upload(uploaded, estensioni: tuple[str, ...]) -> Response | None:
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
    if not uploaded.name.lower().endswith(estensioni):
        return Response(
            {"detail": f"Tipo di file non supportato. Usa: {', '.join(estensioni)}."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None


class CorpusListView(ListAPIView):
    """Elenco dei documenti del corpus, opzionalmente filtrato per categoria."""

    serializer_class = DocumentoCorpusSerializer

    def get_queryset(self):
        qs = _documenti_visibili(self.request.user)
        categoria = self.request.query_params.get("categoria")
        if categoria:
            qs = qs.filter(categoria=categoria)
        return qs


def _estrai_da_file(uploaded) -> str:
    """Estrae il testo da un file caricato (PDF nativo o testo)."""
    nome = uploaded.name.lower()
    contenuto = uploaded.read()
    if nome.endswith(".pdf"):
        import fitz

        with fitz.open(stream=contenuto, filetype="pdf") as doc:
            return "\n".join(p.get_text("text") for p in doc).strip()
    return contenuto.decode("utf-8", errors="ignore").strip()


class IngestView(APIView):
    """Carica un documento nel corpus (testo o file) e ne avvia l'indicizzazione (async)."""

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        titolo = (request.data.get("titolo") or "").strip()
        testo = (request.data.get("testo") or "").strip()

        upload = request.FILES.get("file")
        if upload is not None and not testo:
            if resp := _valida_upload(upload, _CORPUS_FILE_EXTENSIONS):
                return resp
            try:
                testo = _estrai_da_file(upload)
            except Exception:  # noqa: BLE001
                return Response(
                    {"detail": "Impossibile leggere il file. Usa un PDF nativo o del testo."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            titolo = titolo or upload.name

        if not testo:
            return Response(
                {"detail": "Fornisci un testo o un file (PDF/testo)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        doc = DocumentoCorpus.objects.create(
            titolo=titolo or "Senza titolo",
            fonte=(request.data.get("fonte") or "").strip(),
            categoria=(request.data.get("categoria") or "").strip(),
            testo=testo,
            creato_da=request.user,
        )
        indicizza_documento_task.delay(doc.id)
        return Response(
            DocumentoCorpusSerializer(doc).data, status=status.HTTP_202_ACCEPTED
        )


class CorpusDocumentoView(APIView):
    """Eliminazione di un documento del corpus (cascade sui suoi frammenti)."""

    def delete(self, request, pk):
        doc = get_object_or_404(_documenti_eliminabili(request.user), pk=pk)
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FrammentiView(APIView):
    """Elenco dei frammenti (contenuto) di un documento del corpus."""

    def get(self, request, pk):
        doc = get_object_or_404(_documenti_visibili(request.user), pk=pk)
        return Response(
            [
                {"id": f.id, "ordine": f.ordine, "testo": f.testo}
                for f in doc.frammenti.all()
            ]
        )


class FrammentoView(APIView):
    """Eliminazione di un singolo frammento indicizzato."""

    def delete(self, request, pk):
        frammento = get_object_or_404(FrammentoCorpus.objects.select_related("documento"), pk=pk)
        if not request.user.is_staff and frammento.documento.creato_da_id != request.user.id:
            raise PermissionDenied("Puoi eliminare solo i frammenti dei tuoi documenti.")
        frammento.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CercaView(APIView):
    """Ricerca semantica nel corpus (RAG)."""

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        if not query:
            return Response(
                {"detail": "Parametro 'q' obbligatorio."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            k = min(max(int(request.query_params.get("k", 5)), 1), 20)
        except ValueError:
            k = 5
        frammenti = cerca(
            query, get_embedding_backend(), k=k, documenti=_documenti_visibili(request.user)
        )

        def rilevanza(distanza: float) -> str:
            if distanza <= 0.28:
                return "alta"
            if distanza <= 0.38:
                return "media"
            return "bassa"

        return Response(
            [
                {
                    "documento_id": f.documento_id,
                    "titolo": f.documento.titolo,
                    "fonte": f.documento.fonte,
                    "ordine": f.ordine,
                    "testo": f.testo,
                    "distanza": float(f.distanza),
                    "rilevanza": rilevanza(float(f.distanza)),
                }
                for f in frammenti
            ]
        )
