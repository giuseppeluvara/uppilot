from django.shortcuts import get_object_or_404
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


class CorpusListView(ListAPIView):
    """Elenco dei documenti del corpus, opzionalmente filtrato per categoria."""

    serializer_class = DocumentoCorpusSerializer

    def get_queryset(self):
        qs = DocumentoCorpus.objects.all()
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
        )
        indicizza_documento_task.delay(doc.id)
        return Response(
            DocumentoCorpusSerializer(doc).data, status=status.HTTP_202_ACCEPTED
        )


class CorpusDocumentoView(APIView):
    """Eliminazione di un documento del corpus (cascade sui suoi frammenti)."""

    def delete(self, request, pk):
        doc = get_object_or_404(DocumentoCorpus, pk=pk)
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FrammentiView(APIView):
    """Elenco dei frammenti (contenuto) di un documento del corpus."""

    def get(self, request, pk):
        doc = get_object_or_404(DocumentoCorpus, pk=pk)
        return Response(
            [
                {"id": f.id, "ordine": f.ordine, "testo": f.testo}
                for f in doc.frammenti.all()
            ]
        )


class FrammentoView(APIView):
    """Eliminazione di un singolo frammento indicizzato."""

    def delete(self, request, pk):
        frammento = get_object_or_404(FrammentoCorpus, pk=pk)
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
            k = min(int(request.query_params.get("k", 5)), 20)
        except ValueError:
            k = 5
        frammenti = cerca(query, get_embedding_backend(), k=k)
        return Response(
            [
                {
                    "documento_id": f.documento_id,
                    "titolo": f.documento.titolo,
                    "fonte": f.documento.fonte,
                    "ordine": f.ordine,
                    "testo": f.testo,
                    "distanza": float(f.distanza),
                }
                for f in frammenti
            ]
        )
