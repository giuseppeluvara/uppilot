"""Costruzione asincrona del grafo (estrazione LLM su molti documenti = lunga)."""
from __future__ import annotations

import logging

from celery import shared_task

from ai.factory import get_llm_backend
from apps.casi.models import Lavoro
from apps.corpus.models import DocumentoCorpus

from .models import GrafoMeta
from .services import estrai_grafo_corpus, estrai_grafo_lavoro

logger = logging.getLogger(__name__)


@shared_task
def costruisci_grafo_task(commerciale: bool = False, utente_id: int | None = None) -> None:
    """Costruisce/aggiorna il grafo dal corpus (condiviso) e dai casi dell'utente.

    I nodi del corpus sono globali; i nodi-caso restano legati all'utente che li ha
    generati (lo scoping di visibilità avviene nelle viste).
    """
    meta = GrafoMeta.singleton()
    meta.in_corso = True
    meta.save(update_fields=["in_corso", "aggiornato_at"])
    try:
        llm = get_llm_backend(commerciale)
        for doc in DocumentoCorpus.objects.filter(
            stato=DocumentoCorpus.Stato.COMPLETATO
        ):
            try:
                estrai_grafo_corpus(doc, llm)
            except Exception:  # noqa: BLE001 - un documento non deve fermare il resto
                logger.exception("Estrazione grafo fallita per il corpus %s", doc.id)
        if utente_id is not None:
            for lavoro in Lavoro.objects.filter(
                utente_id=utente_id, analisi_stato=Lavoro.StatoAnalisi.COMPLETATA
            ).prefetch_related("richieste"):
                try:
                    estrai_grafo_lavoro(lavoro, llm)
                except Exception:  # noqa: BLE001
                    logger.exception("Estrazione grafo fallita per il lavoro %s", lavoro.id)
    finally:
        meta.in_corso = False
        meta.save(update_fields=["in_corso", "aggiornato_at"])
