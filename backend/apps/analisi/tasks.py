"""Task asincrono di analisi LLM (§82): la generazione è lunga -> fuori dalla richiesta."""
from __future__ import annotations

import logging

from celery import shared_task
from django.db.models import Q

from ai.factory import (
    get_anonymization_service,
    get_embedding_backend,
    get_legal_search_provider,
    get_llm_backend,
)
from apps.casi.models import Lavoro
from apps.casi.privacy import maschera_residui
from apps.casi.states import StatoLavoro

from .models import Bozza, Richiesta, SpuntoRicerca
from .ricerca import (
    proponi_ricerche,
    pseudonimizza_query,
    sintetizza_spunto,
    _formatta_risultati,
)
from .services import analizza_lavoro, approfondisci_richiesta, documenti_utilizzabili

logger = logging.getLogger(__name__)


def _set_progress(
    lavoro: Lavoro,
    campo: str,
    fase: str,
    *,
    corrente: int = 0,
    totale: int = 1,
    messaggio: str = "",
) -> None:
    totale = max(int(totale or 1), 1)
    corrente = max(min(int(corrente or 0), totale), 0)
    setattr(
        lavoro,
        campo,
        {
            "fase": fase,
            "corrente": corrente,
            "totale": totale,
            "percentuale": round(corrente / totale * 100),
            "messaggio": messaggio,
        },
    )
    lavoro.save(update_fields=[campo])


def _sanifica_lavoro(lavoro: Lavoro, testo: str) -> str:
    return maschera_residui(testo or "", lavoro.mappa_entita or {})


def _sanifica_lista(lavoro: Lavoro, valori) -> list[str]:
    return [_sanifica_lavoro(lavoro, str(x)) for x in (valori or []) if x]


@shared_task
def analizza_lavoro_task(lavoro_id: int, commerciale: bool = False) -> None:
    lavoro = Lavoro.objects.get(pk=lavoro_id)
    lavoro.analisi_stato = Lavoro.StatoAnalisi.IN_CORSO
    lavoro.analisi_errore = ""
    lavoro.analisi_progresso = {
        "fase": "preparazione",
        "corrente": 0,
        "totale": 4,
        "percentuale": 0,
        "messaggio": "Preparazione dei documenti pseudonimizzati",
    }
    lavoro.save(update_fields=["analisi_stato", "analisi_errore", "analisi_progresso"])

    try:
        _set_progress(
            lavoro,
            "analisi_progresso",
            "llm",
            corrente=1,
            totale=4,
            messaggio="Sintesi del fatto ed estrazione delle richieste",
        )
        dati = analizza_lavoro(lavoro, get_llm_backend(commerciale))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Analisi fallita per il lavoro %s", lavoro_id)
        lavoro.analisi_stato = Lavoro.StatoAnalisi.ERRORE
        lavoro.analisi_errore = str(exc)
        lavoro.analisi_task_id = ""
        lavoro.analisi_progresso = {
            "fase": "errore",
            "corrente": 0,
            "totale": 1,
            "percentuale": 0,
            "messaggio": str(exc),
        }
        lavoro.save(
            update_fields=[
                "analisi_stato",
                "analisi_errore",
                "analisi_task_id",
                "analisi_progresso",
            ]
        )
        return

    _set_progress(
        lavoro,
        "analisi_progresso",
        "salvataggio",
        corrente=3,
        totale=4,
        messaggio="Salvataggio di bozza e griglia richieste",
    )
    dati["in_fatto"] = _sanifica_lavoro(lavoro, dati.get("in_fatto", ""))
    for richiesta in dati.get("richieste", []):
        richiesta["testo"] = _sanifica_lavoro(lavoro, richiesta.get("testo", ""))
        richiesta["quesiti_aperti"] = _sanifica_lista(
            lavoro, richiesta.get("quesiti_aperti", [])
        )

    # Persiste la bozza "in fatto".
    Bozza.objects.update_or_create(
        lavoro=lavoro, defaults={"in_fatto": dati["in_fatto"]}
    )

    # Rigenera l'elenco strutturato delle richieste.
    lavoro.richieste.all().delete()
    Richiesta.objects.bulk_create(
        Richiesta(
            lavoro=lavoro,
            parte_richiedente=r["parte"],
            testo=r["testo"],
            quesiti_aperti=r["quesiti_aperti"],
            stato=Richiesta.Stato.ANALIZZATA,
            ordine=i,
        )
        for i, r in enumerate(dati["richieste"])
    )

    # Avanzamento della state machine: analizzato -> bozza generata (§45).
    if lavoro.stato == StatoLavoro.BOZZA_IN_CORSO:
        lavoro.transiziona(StatoLavoro.ANALIZZATO)
    if lavoro.stato == StatoLavoro.ANALIZZATO:
        lavoro.transiziona(StatoLavoro.BOZZA_GENERATA)

    lavoro.analisi_stato = Lavoro.StatoAnalisi.COMPLETATA
    lavoro.analisi_task_id = ""
    lavoro.analisi_progresso = {
        "fase": "completata",
        "corrente": 4,
        "totale": 4,
        "percentuale": 100,
        "messaggio": "Analisi completata",
    }
    lavoro.save(update_fields=["analisi_stato", "analisi_task_id", "analisi_progresso"])


def _riferimenti_corpus(lavoro: Lavoro, testo: str) -> str:
    """Recupera spunti dal corpus per la richiesta (RAG, §83).

    Graceful: se il corpus è vuoto, l'embedding non è disponibile o qualcosa va
    storto, ritorna stringa vuota senza interrompere l'analisi.
    """
    try:
        from apps.corpus.services import cerca
        from apps.corpus.models import DocumentoCorpus

        documenti = DocumentoCorpus.objects.filter(
            Q(creato_da__isnull=True) | Q(creato_da_id=lavoro.utente_id)
        )
        frammenti = cerca(testo, get_embedding_backend(), k=3, documenti=documenti)
        if not frammenti:
            return ""
        return "\n".join(
            f"- [{f.documento.titolo}] {f.testo.strip()[:300]}" for f in frammenti
        )
    except Exception:  # noqa: BLE001 - il RAG è un di più, mai bloccante
        logger.warning("RAG non disponibile per l'approfondimento", exc_info=True)
        return ""


@shared_task
def approfondisci_lavoro_task(lavoro_id: int, commerciale: bool = False) -> None:
    """Ragionamento 'in diritto' su tutte le richieste del lavoro (M2)."""
    lavoro = Lavoro.objects.get(pk=lavoro_id)
    lavoro.approfondimento_stato = Lavoro.StatoAnalisi.IN_CORSO
    lavoro.approfondimento_errore = ""
    richieste = list(lavoro.richieste.all())
    lavoro.approfondimento_progresso = {
        "fase": "preparazione",
        "corrente": 0,
        "totale": max(len(richieste), 1),
        "percentuale": 0,
        "messaggio": "Preparazione richieste e documenti",
    }
    lavoro.save(
        update_fields=[
            "approfondimento_stato",
            "approfondimento_errore",
            "approfondimento_progresso",
        ]
    )

    documenti = list(documenti_utilizzabili(lavoro))
    try:
        llm = get_llm_backend(commerciale)
        totale = max(len(richieste), 1)
        for indice, richiesta in enumerate(richieste, start=1):
            _set_progress(
                lavoro,
                "approfondimento_progresso",
                "richiesta",
                corrente=indice - 1,
                totale=totale,
                messaggio=f"Approfondimento domanda {indice}/{len(richieste)}",
            )
            riferimenti = _riferimenti_corpus(lavoro, richiesta.testo)
            dati = approfondisci_richiesta(richiesta, documenti, llm, riferimenti)
            richiesta.onere_probatorio = _sanifica_lavoro(
                lavoro, dati["onere_probatorio"]
            )
            richiesta.non_contestazioni = _sanifica_lista(
                lavoro, dati["non_contestazioni"]
            )
            richiesta.quesiti_aperti = _sanifica_lista(lavoro, dati["quesiti_aperti"])
            richiesta.stato = Richiesta.Stato.APPROFONDITA
            richiesta.save(
                update_fields=[
                    "onere_probatorio",
                    "non_contestazioni",
                    "quesiti_aperti",
                    "stato",
                ]
            )
            richiesta.allegati_collegati.set(dati["allegati"])
            _set_progress(
                lavoro,
                "approfondimento_progresso",
                "richiesta",
                corrente=indice,
                totale=totale,
                messaggio=f"Domanda {indice}/{len(richieste)} completata",
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Approfondimento fallito per il lavoro %s", lavoro_id)
        lavoro.approfondimento_stato = Lavoro.StatoAnalisi.ERRORE
        lavoro.approfondimento_errore = str(exc)
        lavoro.approfondimento_task_id = ""
        lavoro.approfondimento_progresso = {
            "fase": "errore",
            "corrente": 0,
            "totale": 1,
            "percentuale": 0,
            "messaggio": str(exc),
        }
        lavoro.save(
            update_fields=[
                "approfondimento_stato",
                "approfondimento_errore",
                "approfondimento_task_id",
                "approfondimento_progresso",
            ]
        )
        return

    lavoro.approfondimento_stato = Lavoro.StatoAnalisi.COMPLETATA
    lavoro.approfondimento_task_id = ""
    lavoro.approfondimento_progresso = {
        "fase": "completata",
        "corrente": max(len(richieste), 1),
        "totale": max(len(richieste), 1),
        "percentuale": 100,
        "messaggio": "Approfondimento completato",
    }
    lavoro.save(
        update_fields=[
            "approfondimento_stato",
            "approfondimento_task_id",
            "approfondimento_progresso",
        ]
    )


@shared_task
def ricerca_spunti_task(lavoro_id: int, commerciale: bool = False) -> None:
    """Ricerca giuridica 'spunti' via web search (§6). Query pseudonimizzata (§134)."""
    lavoro = Lavoro.objects.get(pk=lavoro_id)
    lavoro.ricerca_stato = Lavoro.StatoAnalisi.IN_CORSO
    lavoro.ricerca_errore = ""
    lavoro.ricerca_progresso = {
        "fase": "preparazione",
        "corrente": 0,
        "totale": 3,
        "percentuale": 0,
        "messaggio": "Preparazione delle query giuridiche",
    }
    lavoro.save(update_fields=["ricerca_stato", "ricerca_errore", "ricerca_progresso"])

    try:
        llm = get_llm_backend(commerciale)
        provider = get_legal_search_provider()
        anon = get_anonymization_service()

        _set_progress(
            lavoro,
            "ricerca_progresso",
            "query",
            corrente=0,
            totale=3,
            messaggio="Generazione query pseudonimizzate",
        )
        ricerche = proponi_ricerche(lavoro, llm)
        lavoro.spunti.filter(origine=SpuntoRicerca.Origine.WEB).delete()
        totale = max(len(ricerche), 1)
        for indice, ricerca in enumerate(ricerche, start=1):
            _set_progress(
                lavoro,
                "ricerca_progresso",
                "web",
                corrente=indice - 1,
                totale=totale,
                messaggio=f"Ricerca fonte {indice}/{len(ricerche)}",
            )
            query = pseudonimizza_query(ricerca["query"], anon)
            risultati = provider.search(query)
            dati = sintetizza_spunto(
                ricerca["argomento"], query, _formatta_risultati(risultati), llm
            )
            SpuntoRicerca.objects.create(
                lavoro=lavoro,
                query_pseudonimizzata=query,
                argomento=ricerca["argomento"],
                sintesi=_sanifica_lavoro(lavoro, dati["sintesi"]),
                suggerimento=_sanifica_lavoro(lavoro, dati["suggerimento"]),
                fonte=risultati[0].fonte if risultati else "",
                origine=SpuntoRicerca.Origine.WEB,
            )
            _set_progress(
                lavoro,
                "ricerca_progresso",
                "web",
                corrente=indice,
                totale=totale,
                messaggio=f"Spunto {indice}/{len(ricerche)} creato",
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ricerca spunti fallita per il lavoro %s", lavoro_id)
        lavoro.ricerca_stato = Lavoro.StatoAnalisi.ERRORE
        lavoro.ricerca_errore = str(exc)
        lavoro.ricerca_task_id = ""
        lavoro.ricerca_progresso = {
            "fase": "errore",
            "corrente": 0,
            "totale": 1,
            "percentuale": 0,
            "messaggio": str(exc),
        }
        lavoro.save(
            update_fields=[
                "ricerca_stato",
                "ricerca_errore",
                "ricerca_task_id",
                "ricerca_progresso",
            ]
        )
        return

    lavoro.ricerca_stato = Lavoro.StatoAnalisi.COMPLETATA
    lavoro.ricerca_task_id = ""
    lavoro.ricerca_progresso = {
        "fase": "completata",
        "corrente": 1,
        "totale": 1,
        "percentuale": 100,
        "messaggio": "Ricerca completata",
    }
    lavoro.save(update_fields=["ricerca_stato", "ricerca_task_id", "ricerca_progresso"])


@shared_task
def ricerca_manuale_task(
    lavoro_id: int, argomento: str, materiale: str, commerciale: bool = False
) -> None:
    """Sintetizza uno spunto da risultati incollati manualmente dall'utente (§137)."""
    lavoro = Lavoro.objects.get(pk=lavoro_id)
    lavoro.ricerca_stato = Lavoro.StatoAnalisi.IN_CORSO
    lavoro.ricerca_errore = ""
    lavoro.ricerca_progresso = {
        "fase": "manuale",
        "corrente": 0,
        "totale": 2,
        "percentuale": 0,
        "messaggio": "Sintesi dei risultati incollati",
    }
    lavoro.save(update_fields=["ricerca_stato", "ricerca_errore", "ricerca_progresso"])

    try:
        dati = sintetizza_spunto(
            argomento, "", materiale, get_llm_backend(commerciale), origine="manuale"
        )
        _set_progress(
            lavoro,
            "ricerca_progresso",
            "manuale",
            corrente=1,
            totale=2,
            messaggio="Salvataggio dello spunto manuale",
        )
        SpuntoRicerca.objects.create(
            lavoro=lavoro,
            argomento=argomento,
            sintesi=_sanifica_lavoro(lavoro, dati["sintesi"]),
            suggerimento=_sanifica_lavoro(lavoro, dati["suggerimento"]),
            origine=SpuntoRicerca.Origine.MANUALE,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ricerca manuale fallita per il lavoro %s", lavoro_id)
        lavoro.ricerca_stato = Lavoro.StatoAnalisi.ERRORE
        lavoro.ricerca_errore = str(exc)
        lavoro.ricerca_task_id = ""
        lavoro.ricerca_progresso = {
            "fase": "errore",
            "corrente": 0,
            "totale": 1,
            "percentuale": 0,
            "messaggio": str(exc),
        }
        lavoro.save(
            update_fields=[
                "ricerca_stato",
                "ricerca_errore",
                "ricerca_task_id",
                "ricerca_progresso",
            ]
        )
        return

    lavoro.ricerca_stato = Lavoro.StatoAnalisi.COMPLETATA
    lavoro.ricerca_task_id = ""
    lavoro.ricerca_progresso = {
        "fase": "completata",
        "corrente": 2,
        "totale": 2,
        "percentuale": 100,
        "messaggio": "Spunto manuale creato",
    }
    lavoro.save(update_fields=["ricerca_stato", "ricerca_task_id", "ricerca_progresso"])
