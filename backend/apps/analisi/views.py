from celery import current_app
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from ai.factory import commerciale_disponibile
from apps.casi.models import Documento, Lavoro
from apps.casi.privacy import privacy_report

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


def _fase_gia_in_corso(lavoro: Lavoro, campo_stato: str, nome: str):
    if getattr(lavoro, campo_stato) != Lavoro.StatoAnalisi.IN_CORSO:
        return None
    return Response(
        {"detail": f"{nome} già in corso. Interrompila o attendi il completamento."},
        status=status.HTTP_409_CONFLICT,
    )


def _marca_in_corso(
    lavoro: Lavoro,
    campo_stato: str,
    campo_errore: str,
    campo_progresso: str | None = None,
    messaggio: str = "Elaborazione avviata",
) -> None:
    setattr(lavoro, campo_stato, Lavoro.StatoAnalisi.IN_CORSO)
    setattr(lavoro, campo_errore, "")
    campi = [campo_stato, campo_errore]
    if campo_progresso:
        setattr(
            lavoro,
            campo_progresso,
            {
                "fase": "avvio",
                "corrente": 0,
                "totale": 1,
                "percentuale": 0,
                "messaggio": messaggio,
            },
        )
        campi.append(campo_progresso)
    lavoro.save(update_fields=campi)


def _salva_task_id_se_ancora_in_corso(
    lavoro: Lavoro, campo_stato: str, campo_task: str, task_id: str
) -> None:
    lavoro.refresh_from_db(fields=[campo_stato])
    setattr(
        lavoro,
        campo_task,
        task_id if getattr(lavoro, campo_stato) == Lavoro.StatoAnalisi.IN_CORSO else "",
    )
    lavoro.save(update_fields=[campo_task])


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


def _documenti_da_verificare(lavoro: Lavoro):
    return Documento.objects.filter(
        sezione__lavoro=lavoro,
        pseudonimizzato=True,
        stato_accettazione=Documento.StatoAccettazione.DA_VERIFICARE,
    )


class AvviaAnalisiView(APIView):
    """Avvia l'analisi LLM del lavoro (asincrona)."""

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        if resp := _fase_gia_in_corso(lavoro, "analisi_stato", "Analisi"):
            return resp
        if not documenti_utilizzabili(lavoro).exists():
            return Response(
                {"detail": "Nessun documento utilizzabile: caricane e accettane almeno uno."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        non_accettati = _documenti_da_verificare(lavoro).count()
        if non_accettati and not request.data.get("conferma_parziale"):
            return Response(
                {
                    "detail": (
                        f"Ci sono {non_accettati} documenti pseudonimizzati non ancora "
                        "accettati. Conferma esplicitamente l'analisi parziale o rivedili prima."
                    ),
                    "code": "analisi_parziale_da_confermare",
                    "documenti_non_accettati": non_accettati,
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            commerciale, warning = _opt_in_commerciale(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        _marca_in_corso(
            lavoro,
            "analisi_stato",
            "analisi_errore",
            "analisi_progresso",
            "Analisi avviata",
        )
        res = analizza_lavoro_task.delay(lavoro.id, commerciale)
        _salva_task_id_se_ancora_in_corso(lavoro, "analisi_stato", "analisi_task_id", res.id)
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
        if resp := _fase_gia_in_corso(lavoro, "approfondimento_stato", "Approfondimento"):
            return resp
        if not lavoro.richieste.exists():
            return Response(
                {"detail": "Nessuna richiesta: esegui prima l'analisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            commerciale, warning = _opt_in_commerciale(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        _marca_in_corso(
            lavoro,
            "approfondimento_stato",
            "approfondimento_errore",
            "approfondimento_progresso",
            "Approfondimento avviato",
        )
        res = approfondisci_lavoro_task.delay(lavoro.id, commerciale)
        _salva_task_id_se_ancora_in_corso(
            lavoro, "approfondimento_stato", "approfondimento_task_id", res.id
        )
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
        if resp := _fase_gia_in_corso(lavoro, "ricerca_stato", "Ricerca"):
            return resp
        try:
            commerciale, warning = _opt_in_commerciale(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        _marca_in_corso(
            lavoro,
            "ricerca_stato",
            "ricerca_errore",
            "ricerca_progresso",
            "Ricerca avviata",
        )
        res = ricerca_spunti_task.delay(lavoro.id, commerciale)
        _salva_task_id_se_ancora_in_corso(lavoro, "ricerca_stato", "ricerca_task_id", res.id)
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
        if resp := _fase_gia_in_corso(lavoro, "ricerca_stato", "Ricerca"):
            return resp
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
        _marca_in_corso(
            lavoro,
            "ricerca_stato",
            "ricerca_errore",
            "ricerca_progresso",
            "Sintesi manuale avviata",
        )
        res = ricerca_manuale_task.delay(
            lavoro.id, (request.data.get("argomento") or "").strip(), materiale, commerciale
        )
        _salva_task_id_se_ancora_in_corso(lavoro, "ricerca_stato", "ricerca_task_id", res.id)
        return Response(
            {"detail": "Spunto in elaborazione.", "warning": warning},
            status=status.HTTP_202_ACCEPTED,
        )


# Fase -> (campo task_id, campo stato, campo errore) sul modello Lavoro.
FASI_ANNULLABILI = {
    "analisi": (
        "analisi_task_id",
        "analisi_stato",
        "analisi_errore",
        "analisi_progresso",
    ),
    "approfondimento": (
        "approfondimento_task_id",
        "approfondimento_stato",
        "approfondimento_errore",
        "approfondimento_progresso",
    ),
    "ricerca": (
        "ricerca_task_id",
        "ricerca_stato",
        "ricerca_errore",
        "ricerca_progresso",
    ),
}


class AnnullaAnalisiView(APIView):
    """Interrompe un'elaborazione in corso revocando il task Celery (§82).

    Utile se l'utente l'ha avviata per errore o vuole prima modificare i documenti.
    Riporta la fase a 'in attesa' così può essere rilanciata.
    """

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        fase = request.data.get("fase")
        if fase not in FASI_ANNULLABILI:
            return Response(
                {"detail": "Fase non valida: usa 'analisi', 'approfondimento' o 'ricerca'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        campo_task, campo_stato, campo_errore, campo_progresso = FASI_ANNULLABILI[fase]

        task_id = getattr(lavoro, campo_task)
        if task_id:
            # terminate=True ferma anche il task già in esecuzione (non solo in coda).
            current_app.control.revoke(task_id, terminate=True, signal="SIGTERM")

        # Rilegge lo stato fresco dal DB: il task potrebbe essersi concluso tra il
        # caricamento del lavoro e ora; senza questo scriveremmo 'in attesa' sopra
        # un esito 'completata' già persistito (race), perdendolo nella UI.
        lavoro.refresh_from_db(fields=[campo_stato])

        campi = [campo_task]
        setattr(lavoro, campo_task, "")
        # Riporta a 'in attesa' solo se è davvero in corso: evita di azzerare un
        # esito appena concluso (race tra revoke e completamento del task).
        if getattr(lavoro, campo_stato) == Lavoro.StatoAnalisi.IN_CORSO:
            setattr(lavoro, campo_stato, Lavoro.StatoAnalisi.IN_ATTESA)
            setattr(lavoro, campo_errore, "")
            setattr(
                lavoro,
                campo_progresso,
                {
                    "fase": "interrotta",
                    "corrente": 0,
                    "totale": 1,
                    "percentuale": 0,
                    "messaggio": "Elaborazione interrotta dall'utente",
                },
            )
            campi += [campo_stato, campo_errore, campo_progresso]
        lavoro.save(update_fields=campi)
        return Response({"detail": "Elaborazione interrotta."}, status=status.HTTP_200_OK)


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
        if not in_chiaro and request.query_params.get("force_privacy") != "1":
            testi = []
            bozza = Bozza.objects.filter(lavoro=lavoro).first()
            if bozza:
                testi.extend([bozza.in_fatto, bozza.pqm])
            for r in lavoro.richieste.all():
                testi.extend(
                    [
                        r.testo,
                        r.onere_probatorio,
                        r.motivazione,
                        "\n".join(r.non_contestazioni or []),
                        "\n".join(r.quesiti_aperti or []),
                    ]
                )
            report = privacy_report(testi, lavoro.mappa_entita or {}, extra_values=[lavoro.titolo])
            if not report["ok"]:
                return Response(
                    {
                        "detail": (
                            "Il controllo privacy segnala possibili residui. "
                            "Rivedi il testo o conferma esplicitamente l'override."
                        ),
                        "privacy_report": report,
                    },
                    status=status.HTTP_409_CONFLICT,
                )
        contenuto = genera_docx(lavoro, in_chiaro=in_chiaro)
        suffisso = "_in_chiaro" if in_chiaro else ""
        resp = HttpResponse(contenuto, content_type=DOCX_CONTENT_TYPE)
        resp["Content-Disposition"] = f'attachment; filename="bozza_{lavoro.id}{suffisso}.docx"'
        return resp
