from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from ai.factory import commerciale_disponibile
from apps.casi.models import Lavoro

from .export import genera_docx
from .models import Bozza, Richiesta, SpuntoRicerca
from .serializers import BozzaSerializer, RichiestaSerializer, SpuntoRicercaSerializer
from .services import documenti_utilizzabili
from .tasks import (
    analizza_lavoro_task,
    approfondisci_lavoro_task,
    ricerca_manuale_task,
    ricerca_spunti_task,
)

DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _lavoro_utente(request, lavoro_id) -> Lavoro:
    return get_object_or_404(Lavoro, pk=lavoro_id, utente=request.user)


# Warning inequivocabile per l'uso di LLM commerciale in cloud (§5/§125).
WARNING_COMMERCIALE = (
    "Stai inviando testo PSEUDONIMIZZATO (non anonimizzato) a un LLM commerciale "
    "in cloud: ai fini del GDPR resta dato personale. Procedi solo se consapevole."
)


def _opt_in_commerciale(request):
    """Legge il flag opt-in LLM commerciale e lo valida (§5).

    Ritorna (commerciale: bool, warning: str|None). Solleva ValueError se
    richiesto ma non configurato (gestito dal chiamante come 400).
    """
    commerciale = bool(request.data.get("commerciale"))
    if commerciale and not commerciale_disponibile():
        raise ValueError("LLM commerciale non configurato (manca la chiave API).")
    return commerciale, (WARNING_COMMERCIALE if commerciale else None)


class AvviaAnalisiView(APIView):
    """Avvia l'analisi LLM del lavoro (asincrona)."""

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        if not documenti_utilizzabili(lavoro).exists():
            return Response(
                {"detail": "Nessun documento utilizzabile: caricane e accettane almeno uno."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            commerciale, warning = _opt_in_commerciale(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        analizza_lavoro_task.delay(lavoro.id, commerciale)
        return Response(
            {
                "detail": "Analisi avviata.",
                "analisi_stato": Lavoro.StatoAnalisi.IN_CORSO,
                "warning": warning,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ApprofondisciView(APIView):
    """Avvia il ragionamento 'in diritto' su tutte le richieste del lavoro (M2)."""

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        if not lavoro.richieste.exists():
            return Response(
                {"detail": "Nessuna richiesta: esegui prima l'analisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            commerciale, warning = _opt_in_commerciale(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        approfondisci_lavoro_task.delay(lavoro.id, commerciale)
        return Response(
            {
                "detail": "Approfondimento avviato.",
                "approfondimento_stato": Lavoro.StatoAnalisi.IN_CORSO,
                "warning": warning,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class AvviaRicercaView(APIView):
    """Avvia la ricerca giuridica 'spunti' via web (§6, async)."""

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        try:
            commerciale, warning = _opt_in_commerciale(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        ricerca_spunti_task.delay(lavoro.id, commerciale)
        return Response(
            {
                "detail": "Ricerca avviata.",
                "ricerca_stato": Lavoro.StatoAnalisi.IN_CORSO,
                "warning": warning,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class RicercaManualeView(APIView):
    """Sintetizza uno spunto dai risultati incollati manualmente (§137)."""

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        materiale = (request.data.get("materiale") or "").strip()
        if not materiale:
            return Response(
                {"detail": "Incolla i risultati nel campo 'materiale'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            commerciale, warning = _opt_in_commerciale(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        ricerca_manuale_task.delay(
            lavoro.id, (request.data.get("argomento") or "").strip(), materiale, commerciale
        )
        return Response(
            {"detail": "Spunto in elaborazione.", "warning": warning},
            status=status.HTTP_202_ACCEPTED,
        )


class SpuntiListView(ListAPIView):
    """Elenco degli spunti di approfondimento del lavoro."""

    serializer_class = SpuntoRicercaSerializer

    def get_queryset(self):
        lavoro = _lavoro_utente(self.request, self.kwargs["lavoro_id"])
        return SpuntoRicerca.objects.filter(lavoro=lavoro)


class RichiesteListView(ListAPIView):
    """Elenco strutturato delle richieste analizzate di un lavoro."""

    serializer_class = RichiestaSerializer

    def get_queryset(self):
        lavoro = _lavoro_utente(self.request, self.kwargs["lavoro_id"])
        return Richiesta.objects.filter(lavoro=lavoro)


class RichiestaUpdateView(APIView):
    """Editor: l'operatore redige la motivazione 'in diritto' di una richiesta (§1)."""

    def patch(self, request, pk):
        richiesta = get_object_or_404(Richiesta, pk=pk, lavoro__utente=request.user)
        motivazione = request.data.get("motivazione")
        if motivazione is not None:
            richiesta.motivazione = motivazione
            richiesta.save(update_fields=["motivazione"])
        return Response(RichiestaSerializer(richiesta).data)


class BozzaView(APIView):
    """Restituisce la bozza 'in fatto' del lavoro."""

    def get(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        bozza = Bozza.objects.filter(lavoro=lavoro).first()
        if bozza is None:
            return Response(
                {"detail": "Bozza non ancora generata."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(BozzaSerializer(bozza).data)

    def patch(self, request, lavoro_id):
        """Editor: l'utente modifica la bozza 'in fatto' e/o il P.Q.M."""
        lavoro = _lavoro_utente(request, lavoro_id)
        bozza = get_object_or_404(Bozza, lavoro=lavoro)
        campi = []
        for campo in ("in_fatto", "pqm"):
            valore = request.data.get(campo)
            if valore is not None:
                setattr(bozza, campo, valore)
                campi.append(campo)
        if campi:
            bozza.versione += 1
            bozza.save(update_fields=[*campi, "versione", "updated_at"])
        return Response(BozzaSerializer(bozza).data)


class EsportaDocxView(APIView):
    """Scarica la bozza come documento Word (.docx) — §7."""

    def get(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        in_chiaro = request.query_params.get("chiaro") == "1"
        contenuto = genera_docx(lavoro, in_chiaro=in_chiaro)
        suffisso = "_in_chiaro" if in_chiaro else ""
        resp = HttpResponse(contenuto, content_type=DOCX_CONTENT_TYPE)
        resp["Content-Disposition"] = f'attachment; filename="bozza_{lavoro.id}{suffisso}.docx"'
        return resp
