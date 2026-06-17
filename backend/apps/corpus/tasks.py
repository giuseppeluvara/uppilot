"""Task asincrono di indicizzazione del corpus (§82): l'embedding è lungo."""
from __future__ import annotations

import logging

from celery import shared_task

from ai.factory import get_embedding_backend

from .models import DocumentoCorpus
from .services import indicizza

logger = logging.getLogger(__name__)


@shared_task
def indicizza_documento_task(documento_id: int) -> None:
    doc = DocumentoCorpus.objects.get(pk=documento_id)
    doc.stato = DocumentoCorpus.Stato.IN_CORSO
    doc.errore = ""
    doc.save(update_fields=["stato", "errore"])
    try:
        indicizza(doc, get_embedding_backend())
    except Exception as exc:  # noqa: BLE001
        logger.exception("Indicizzazione corpus fallita per %s", documento_id)
        doc.stato = DocumentoCorpus.Stato.ERRORE
        doc.errore = str(exc)
        doc.save(update_fields=["stato", "errore"])
        return
    doc.stato = DocumentoCorpus.Stato.COMPLETATO
    doc.save(update_fields=["stato"])
