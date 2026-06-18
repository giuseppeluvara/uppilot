"""Costruzione asincrona del grafo (estrazione LLM su molti documenti = lunga)."""
from __future__ import annotations

import logging

from celery import shared_task

from ai.factory import get_llm_backend
from apps.corpus.models import DocumentoCorpus

from .models import GrafoMeta
from .services import estrai_grafo_corpus

logger = logging.getLogger(__name__)


@shared_task
def costruisci_grafo_task(commerciale: bool = False) -> None:
    """Costruisce/aggiorna il grafo dai documenti del corpus indicizzati."""
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
    finally:
        meta.in_corso = False
        meta.save(update_fields=["in_corso", "aggiornato_at"])
