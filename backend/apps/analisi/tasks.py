"""Task asincrono di analisi LLM (§82): la generazione è lunga -> fuori dalla richiesta."""
from __future__ import annotations

import logging

from celery import shared_task

from ai.factory import (
    get_anonymization_service,
    get_embedding_backend,
    get_legal_search_provider,
    get_llm_backend,
)
from apps.casi.models import Lavoro
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


@shared_task
def analizza_lavoro_task(lavoro_id: int, commerciale: bool = False) -> None:
    lavoro = Lavoro.objects.get(pk=lavoro_id)
    lavoro.analisi_stato = Lavoro.StatoAnalisi.IN_CORSO
    lavoro.analisi_errore = ""
    lavoro.save(update_fields=["analisi_stato", "analisi_errore"])

    try:
        dati = analizza_lavoro(lavoro, get_llm_backend(commerciale))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Analisi fallita per il lavoro %s", lavoro_id)
        lavoro.analisi_stato = Lavoro.StatoAnalisi.ERRORE
        lavoro.analisi_errore = str(exc)
        lavoro.save(update_fields=["analisi_stato", "analisi_errore"])
        return

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
    lavoro.save(update_fields=["analisi_stato"])


def _riferimenti_corpus(testo: str) -> str:
    """Recupera spunti dal corpus per la richiesta (RAG, §83).

    Graceful: se il corpus è vuoto, l'embedding non è disponibile o qualcosa va
    storto, ritorna stringa vuota senza interrompere l'analisi.
    """
    try:
        from apps.corpus.services import cerca

        frammenti = cerca(testo, get_embedding_backend(), k=3)
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
    lavoro.save(update_fields=["approfondimento_stato", "approfondimento_errore"])

    documenti = list(documenti_utilizzabili(lavoro))
    try:
        llm = get_llm_backend(commerciale)
        for richiesta in lavoro.richieste.all():
            riferimenti = _riferimenti_corpus(richiesta.testo)
            dati = approfondisci_richiesta(richiesta, documenti, llm, riferimenti)
            richiesta.onere_probatorio = dati["onere_probatorio"]
            richiesta.non_contestazioni = dati["non_contestazioni"]
            richiesta.quesiti_aperti = dati["quesiti_aperti"]
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
    except Exception as exc:  # noqa: BLE001
        logger.exception("Approfondimento fallito per il lavoro %s", lavoro_id)
        lavoro.approfondimento_stato = Lavoro.StatoAnalisi.ERRORE
        lavoro.approfondimento_errore = str(exc)
        lavoro.save(update_fields=["approfondimento_stato", "approfondimento_errore"])
        return

    lavoro.approfondimento_stato = Lavoro.StatoAnalisi.COMPLETATA
    lavoro.save(update_fields=["approfondimento_stato"])


@shared_task
def ricerca_spunti_task(lavoro_id: int, commerciale: bool = False) -> None:
    """Ricerca giuridica 'spunti' via web search (§6). Query pseudonimizzata (§134)."""
    lavoro = Lavoro.objects.get(pk=lavoro_id)
    lavoro.ricerca_stato = Lavoro.StatoAnalisi.IN_CORSO
    lavoro.ricerca_errore = ""
    lavoro.save(update_fields=["ricerca_stato", "ricerca_errore"])

    try:
        llm = get_llm_backend(commerciale)
        provider = get_legal_search_provider()
        anon = get_anonymization_service()

        lavoro.spunti.filter(origine=SpuntoRicerca.Origine.WEB).delete()
        for ricerca in proponi_ricerche(lavoro, llm):
            query = pseudonimizza_query(ricerca["query"], anon)
            risultati = provider.search(query)
            dati = sintetizza_spunto(
                ricerca["argomento"], query, _formatta_risultati(risultati), llm
            )
            SpuntoRicerca.objects.create(
                lavoro=lavoro,
                query_pseudonimizzata=query,
                argomento=ricerca["argomento"],
                sintesi=dati["sintesi"],
                suggerimento=dati["suggerimento"],
                fonte=risultati[0].fonte if risultati else "",
                origine=SpuntoRicerca.Origine.WEB,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ricerca spunti fallita per il lavoro %s", lavoro_id)
        lavoro.ricerca_stato = Lavoro.StatoAnalisi.ERRORE
        lavoro.ricerca_errore = str(exc)
        lavoro.save(update_fields=["ricerca_stato", "ricerca_errore"])
        return

    lavoro.ricerca_stato = Lavoro.StatoAnalisi.COMPLETATA
    lavoro.save(update_fields=["ricerca_stato"])


@shared_task
def ricerca_manuale_task(
    lavoro_id: int, argomento: str, materiale: str, commerciale: bool = False
) -> None:
    """Sintetizza uno spunto da risultati incollati manualmente dall'utente (§137)."""
    lavoro = Lavoro.objects.get(pk=lavoro_id)
    lavoro.ricerca_stato = Lavoro.StatoAnalisi.IN_CORSO
    lavoro.ricerca_errore = ""
    lavoro.save(update_fields=["ricerca_stato", "ricerca_errore"])

    try:
        dati = sintetizza_spunto(argomento, "", materiale, get_llm_backend(commerciale))
        SpuntoRicerca.objects.create(
            lavoro=lavoro,
            argomento=argomento,
            sintesi=dati["sintesi"],
            suggerimento=dati["suggerimento"],
            origine=SpuntoRicerca.Origine.MANUALE,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ricerca manuale fallita per il lavoro %s", lavoro_id)
        lavoro.ricerca_stato = Lavoro.StatoAnalisi.ERRORE
        lavoro.ricerca_errore = str(exc)
        lavoro.save(update_fields=["ricerca_stato", "ricerca_errore"])
        return

    lavoro.ricerca_stato = Lavoro.StatoAnalisi.COMPLETATA
    lavoro.save(update_fields=["ricerca_stato"])
