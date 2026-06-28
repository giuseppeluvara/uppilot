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

from .export import genera_audit_docx, genera_docx
from .models import Bozza, EventoDecisionale, FattoProcessuale, Richiesta, SpuntoRicerca
from .serializers import (
    BozzaSerializer,
    EventoDecisionaleSerializer,
    FattoProcessualeSerializer,
    RichiestaSerializer,
    SpuntoRicercaSerializer,
)
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


def _testo_fatto_iniziale(richiesta: Richiesta) -> str:
    testo = (richiesta.testo or "").strip()
    if len(testo) <= 320:
        return testo
    return testo[:317].rstrip() + "..."


def _quesito_matrice_iniziale(richiesta: Richiesta) -> str:
    quesiti = [str(q).strip() for q in (richiesta.quesiti_aperti or []) if str(q).strip()]
    if quesiti:
        return quesiti[0]
    if not (richiesta.onere_probatorio or "").strip():
        return "Quali fatti costitutivi/impeditivi e quali prove sorreggono questa richiesta?"
    return ""


def _sincronizza_matrice_lavoro(lavoro: Lavoro) -> None:
    """Crea una prima riga matrice per ogni richiesta priva di fatti.

    La matrice parte minimale: una riga per richiesta. In seguito la riga potrà
    essere spezzata manualmente in più fatti processuali senza perdere il legame
    con la richiesta.
    """

    richieste = list(Richiesta.objects.filter(lavoro=lavoro).order_by("ordine", "id"))
    esistenti = set(
        FattoProcessuale.objects.filter(richiesta__lavoro=lavoro).values_list(
            "richiesta_id", flat=True
        )
    )
    FattoProcessuale.objects.bulk_create(
        FattoProcessuale(
            richiesta=richiesta,
            testo=_testo_fatto_iniziale(richiesta),
            quesito_umano=_quesito_matrice_iniziale(richiesta),
            ordine=0,
        )
        for richiesta in richieste
        if richiesta.id not in esistenti
    )


def _registra_evento(
    *,
    lavoro: Lavoro,
    utente,
    tipo: str,
    descrizione: str = "",
    richiesta: Richiesta | None = None,
    fatto: FattoProcessuale | None = None,
    campo: str = "",
    valore_precedente=None,
    valore_nuovo=None,
) -> None:
    EventoDecisionale.objects.create(
        lavoro=lavoro,
        utente=utente if getattr(utente, "is_authenticated", False) else None,
        richiesta=richiesta,
        fatto=fatto,
        tipo=tipo,
        campo=campo,
        descrizione=descrizione,
        valore_precedente=valore_precedente or {},
        valore_nuovo=valore_nuovo or {},
    )


def _red_team_lavoro(lavoro: Lavoro) -> dict:
    _sincronizza_matrice_lavoro(lavoro)
    issues = []
    righe = (
        FattoProcessuale.objects.filter(richiesta__lavoro=lavoro)
        .select_related("richiesta", "richiesta__lavoro")
        .prefetch_related("richiesta__allegati_collegati")
    )
    for fatto in righe:
        data = FattoProcessualeSerializer(fatto).data
        richiesta = fatto.richiesta
        base = {
            "richiesta_id": richiesta.id,
            "fatto_id": fatto.id,
            "richiesta": richiesta.testo,
        }
        if data["fonti_count"] == 0:
            issues.append(
                {
                    **base,
                    "severita": "alta",
                    "ambito": "prove",
                    "messaggio": "Richiesta senza fonti interne agganciate.",
                    "azione_suggerita": "Collega documenti o marca il fatto come non provato/insufficiente.",
                }
            )
        elif data["score_massimo"] < 0.45:
            issues.append(
                {
                    **base,
                    "severita": "media",
                    "ambito": "prove",
                    "messaggio": "Fonti presenti ma con score debole.",
                    "azione_suggerita": "Verifica manualmente snippet e pertinenza della fonte.",
                }
            )
        if data["stato_suggerito"] == FattoProcessuale.StatoProva.INSUFFICIENTE and fatto.stato_prova == FattoProcessuale.StatoProva.PROVATO:
            issues.append(
                {
                    **base,
                    "severita": "alta",
                    "ambito": "stato prova",
                    "messaggio": "La riga è marcata provata, ma il sistema suggerisce insufficienza.",
                    "azione_suggerita": "Motiva nelle note perché il fatto è provato o cambia stato prova.",
                }
            )
        if richiesta.quesiti_aperti and fatto.stato_prova == FattoProcessuale.StatoProva.PROVATO:
            issues.append(
                {
                    **base,
                    "severita": "media",
                    "ambito": "decisione umana",
                    "messaggio": "Fatto marcato provato nonostante quesiti aperti.",
                    "azione_suggerita": "Risolvi i quesiti o sposta lo stato su da decidere/controverso.",
                }
            )
        if fatto.stato_contraddittorio == FattoProcessuale.StatoContraddittorio.SILENTE and not fatto.note_contraddittorio:
            issues.append(
                {
                    **base,
                    "severita": "bassa",
                    "ambito": "contraddittorio",
                    "messaggio": "Controparte silente senza nota esplicativa.",
                    "azione_suggerita": "Annota se il silenzio equivale a non contestazione o richiede verifica.",
                }
            )
        if data["fonti_controparte"] and fatto.stato_contraddittorio in {
            FattoProcessuale.StatoContraddittorio.NON_CONTESTATO,
            FattoProcessuale.StatoContraddittorio.PACIFICO,
        }:
            issues.append(
                {
                    **base,
                    "severita": "alta",
                    "ambito": "contraddittorio",
                    "messaggio": "Sono presenti fonti della controparte ma il contraddittorio è marcato pacifico/non contestato.",
                    "azione_suggerita": "Rivedi lo stato del contraddittorio o motiva la non contestazione.",
                }
            )
        if not (richiesta.motivazione or "").strip():
            issues.append(
                {
                    **base,
                    "severita": "media",
                    "ambito": "motivazione",
                    "messaggio": "Motivazione in diritto non compilata.",
                    "azione_suggerita": "Completa la motivazione o lascia un quesito umano esplicito.",
                }
            )
        if richiesta.motivazione and fatto.stato_prova in {
            FattoProcessuale.StatoProva.NON_PROVATO,
            FattoProcessuale.StatoProva.INSUFFICIENTE,
        }:
            issues.append(
                {
                    **base,
                    "severita": "alta",
                    "ambito": "motivazione/prova",
                    "messaggio": "Motivazione presente su una riga marcata non provata o insufficiente.",
                    "azione_suggerita": "Allinea motivazione e stato prova prima dell'export.",
                }
            )

    bozza = Bozza.objects.filter(lavoro=lavoro).first()
    if not bozza or not (bozza.pqm or "").strip():
        issues.append(
            {
                "richiesta_id": None,
                "fatto_id": None,
                "richiesta": "",
                "severita": "alta",
                "ambito": "PQM",
                "messaggio": "P.Q.M. non compilato.",
                "azione_suggerita": "Compila il dispositivo prima della revisione finale.",
            }
        )
    elif any(not (r.motivazione or "").strip() for r in lavoro.richieste.all()):
        issues.append(
            {
                "richiesta_id": None,
                "fatto_id": None,
                "richiesta": "",
                "severita": "alta",
                "ambito": "PQM/motivazione",
                "messaggio": "P.Q.M. compilato con una o più motivazioni mancanti.",
                "azione_suggerita": "Completa le motivazioni prima di consolidare il dispositivo.",
            }
        )

    conteggi = {
        "alta": sum(1 for i in issues if i["severita"] == "alta"),
        "media": sum(1 for i in issues if i["severita"] == "media"),
        "bassa": sum(1 for i in issues if i["severita"] == "bassa"),
    }
    return {"ok": not issues, "totale": len(issues), "conteggi": conteggi, "issues": issues}


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


class MatriceLavoroView(ListAPIView):
    """Matrice richiesta -> fatto -> prova/lacuna del lavoro."""

    serializer_class = FattoProcessualeSerializer

    def get_queryset(self):
        lavoro = _lavoro_utente(self.request, self.kwargs["lavoro_id"])
        _sincronizza_matrice_lavoro(lavoro)
        return (
            FattoProcessuale.objects.filter(richiesta__lavoro=lavoro)
            .select_related("richiesta", "richiesta__lavoro")
            .prefetch_related("richiesta__allegati_collegati")
            .order_by("richiesta__ordine", "ordine", "id")
        )


class EventiDecisioneListView(ListAPIView):
    """Registro decisionale umano del lavoro."""

    serializer_class = EventoDecisionaleSerializer

    def get_queryset(self):
        lavoro = _lavoro_utente(self.request, self.kwargs["lavoro_id"])
        return EventoDecisionale.objects.filter(lavoro=lavoro).select_related(
            "utente", "richiesta", "fatto"
        )


class RichiestaUpdateView(APIView):
    """Editor: l'operatore redige la motivazione 'in diritto' di una richiesta (§1)."""

    def patch(self, request, pk):
        richiesta = get_object_or_404(Richiesta, pk=pk, lavoro__utente=request.user)
        motivazione = request.data.get("motivazione")
        if motivazione is not None:
            precedente = richiesta.motivazione
            richiesta.motivazione = motivazione
            richiesta.save(update_fields=["motivazione"])
            if precedente != motivazione:
                _registra_evento(
                    lavoro=richiesta.lavoro,
                    utente=request.user,
                    tipo=EventoDecisionale.Tipo.MOTIVAZIONE_AGGIORNATA,
                    richiesta=richiesta,
                    campo="motivazione",
                    descrizione="Motivazione in diritto aggiornata.",
                    valore_precedente={"motivazione": precedente},
                    valore_nuovo={"motivazione": motivazione},
                )
        return Response(RichiestaSerializer(richiesta).data)


class FattoProcessualeUpdateView(APIView):
    """Aggiorna la valutazione umana di una riga della matrice prove."""

    def patch(self, request, pk):
        fatto = get_object_or_404(
            FattoProcessuale,
            pk=pk,
            richiesta__lavoro__utente=request.user,
        )
        campi_tracciati = {
            "testo",
            "stato_prova",
            "funzione_prevalente",
            "stato_contraddittorio",
            "note_operatore",
            "note_contraddittorio",
            "quesito_umano",
        }
        precedente = {c: getattr(fatto, c) for c in campi_tracciati}
        serializer = FattoProcessualeSerializer(fatto, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        fatto.refresh_from_db()
        nuovo = {c: getattr(fatto, c) for c in campi_tracciati}
        cambiati = {c: {"prima": precedente[c], "dopo": nuovo[c]} for c in campi_tracciati if precedente[c] != nuovo[c]}
        if cambiati:
            _registra_evento(
                lavoro=fatto.richiesta.lavoro,
                utente=request.user,
                tipo=EventoDecisionale.Tipo.MATRICE_AGGIORNATA,
                richiesta=fatto.richiesta,
                fatto=fatto,
                campo=", ".join(sorted(cambiati)),
                descrizione="Riga della matrice richieste/prove aggiornata.",
                valore_precedente={c: v["prima"] for c, v in cambiati.items()},
                valore_nuovo={c: v["dopo"] for c, v in cambiati.items()},
            )
        return Response(serializer.data)


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
                precedente = getattr(bozza, campo)
                setattr(bozza, campo, valore)
                campi.append(campo)
                if precedente != valore:
                    _registra_evento(
                        lavoro=lavoro,
                        utente=request.user,
                        tipo=EventoDecisionale.Tipo.BOZZA_AGGIORNATA,
                        campo=campo,
                        descrizione=f"Campo bozza aggiornato: {campo}.",
                        valore_precedente={campo: precedente},
                        valore_nuovo={campo: valore},
                    )
        if campi:
            bozza.versione += 1
            bozza.save(update_fields=[*campi, "versione", "updated_at"])
        return Response(BozzaSerializer(bozza).data)


class EsportaAuditDocxView(APIView):
    """Scarica l'allegato audit della matrice e del registro decisionale."""

    def get(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        _sincronizza_matrice_lavoro(lavoro)
        contenuto = genera_audit_docx(lavoro)
        _registra_evento(
            lavoro=lavoro,
            utente=request.user,
            tipo=EventoDecisionale.Tipo.AUDIT_ESPORTATO,
            descrizione="Allegato audit esportato.",
        )
        resp = HttpResponse(contenuto, content_type=DOCX_CONTENT_TYPE)
        resp["Content-Disposition"] = f'attachment; filename="audit_lavoro_{lavoro.id}.docx"'
        return resp


class RedTeamFascicoloView(APIView):
    """Controllo critico su richieste, prove, motivazione e P.Q.M."""

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        report = _red_team_lavoro(lavoro)
        _registra_evento(
            lavoro=lavoro,
            utente=request.user,
            tipo=EventoDecisionale.Tipo.RED_TEAM_ESEGUITO,
            descrizione="Red team del fascicolo eseguito.",
            valore_nuovo={
                "totale": report["totale"],
                "conteggi": report["conteggi"],
            },
        )
        return Response(report)


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
                        "\n".join(
                            str(f.get("snippet", ""))
                            for f in (r.fonti_tracciate or [])
                            if isinstance(f, dict)
                        ),
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
