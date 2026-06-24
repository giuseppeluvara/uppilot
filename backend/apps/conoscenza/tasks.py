"""Costruzione asincrona del grafo (estrazione LLM su molti documenti = lunga)."""
from __future__ import annotations

import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.db.models import Q

from ai.factory import get_llm_backend
from apps.casi.models import Lavoro
from apps.corpus.models import DocumentoCorpus

from .models import GrafoMeta
from .services import estrai_grafo_corpus, estrai_grafo_lavoro

logger = logging.getLogger(__name__)


def _set_progress(meta: GrafoMeta, fase: str, corrente: int, totale: int, messaggio: str):
    totale = max(totale, 1)
    corrente = max(min(corrente, totale), 0)
    meta.progresso = {
        "fase": fase,
        "corrente": corrente,
        "totale": totale,
        "percentuale": round(corrente / totale * 100),
        "messaggio": messaggio,
    }
    meta.save(update_fields=["progresso", "aggiornato_at"])


@shared_task
def costruisci_grafo_task(commerciale: bool = False, utente_id: int | None = None) -> None:
    """Costruisce/aggiorna il grafo dal corpus (condiviso) e dai casi dell'utente.

    I nodi del corpus sono globali; i nodi-caso restano legati all'utente che li ha
    generati (lo scoping di visibilità avviene nelle viste).
    """
    meta = GrafoMeta.singleton()
    meta.in_corso = True
    meta.progresso = {
        "fase": "preparazione",
        "corrente": 0,
        "totale": 1,
        "percentuale": 0,
        "messaggio": "Preparazione corpus e fascicoli",
    }
    meta.save(update_fields=["in_corso", "progresso", "aggiornato_at"])
    try:
        llm = get_llm_backend(commerciale)
        corpus = DocumentoCorpus.objects.filter(stato=DocumentoCorpus.Stato.COMPLETATO)
        if utente_id is not None:
            user = get_user_model().objects.filter(pk=utente_id).first()
            if user and not user.is_staff:
                corpus = corpus.filter(Q(creato_da__isnull=True) | Q(creato_da_id=utente_id))
        corpus = list(corpus)
        lavori = []
        if utente_id is not None:
            lavori = list(
                Lavoro.objects.filter(
                    utente_id=utente_id, analisi_stato=Lavoro.StatoAnalisi.COMPLETATA
                ).prefetch_related("richieste")
            )
        totale = max(len(corpus) + len(lavori), 1)
        corrente = 0
        for doc in corpus:
            _set_progress(
                meta,
                "corpus",
                corrente,
                totale,
                f"Estrazione concetti dal corpus: {doc.titolo}",
            )
            try:
                estrai_grafo_corpus(doc, llm)
            except Exception:  # noqa: BLE001 - un documento non deve fermare il resto
                logger.exception("Estrazione grafo fallita per il corpus %s", doc.id)
            corrente += 1
            _set_progress(meta, "corpus", corrente, totale, "Documento corpus completato")
        for lavoro in lavori:
            _set_progress(
                meta,
                "fascicoli",
                corrente,
                totale,
                f"Estrazione concetti dal fascicolo #{lavoro.id}",
            )
            try:
                estrai_grafo_lavoro(lavoro, llm)
            except Exception:  # noqa: BLE001
                logger.exception("Estrazione grafo fallita per il lavoro %s", lavoro.id)
            corrente += 1
            _set_progress(meta, "fascicoli", corrente, totale, "Fascicolo completato")
    finally:
        meta.in_corso = False
        meta.progresso = {
            "fase": "completata",
            "corrente": 1,
            "totale": 1,
            "percentuale": 100,
            "messaggio": "Grafo aggiornato",
        }
        meta.save(update_fields=["in_corso", "progresso", "aggiornato_at"])
