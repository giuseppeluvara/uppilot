"""Task asincroni dell'app casi (§82): OCR/estrazione fuori dal ciclo richiesta."""
from __future__ import annotations

import logging
import re

from celery import shared_task
from django.db import transaction

from ai.factory import get_anonymization_service, get_ocr_backend

from .models import Documento, Lavoro
from .services.extraction import estrai_testo

logger = logging.getLogger(__name__)

_RE_GRUPPO = re.compile(r"\[(.+)_\d+\]")


def _gruppo(placeholder: str) -> str:
    """Estrae il gruppo da un placeholder, es. '[PRIVATE_PERSON_3]' -> 'PRIVATE_PERSON'."""
    m = _RE_GRUPPO.match(placeholder)
    return m.group(1) if m else "ENTITA"


def _canonicalizza(lavoro: Lavoro, testo: str, mappa: dict) -> tuple[str, dict]:
    """Rimappa i placeholder del documento su placeholder CANONICI a livello di lavoro.

    Stessa entità reale -> stesso placeholder in tutti i documenti del lavoro.
    Aggiorna `lavoro.mappa_entita` (placeholder canonico -> valore reale). Va eseguito
    sotto select_for_update per evitare race tra documenti pseudonimizzati in parallelo.
    """
    registro = dict(lavoro.mappa_entita)  # canonico -> reale
    inverso = {v: k for k, v in registro.items()}
    contatori: dict[str, int] = {}
    for ph in registro:
        g = _gruppo(ph)
        try:
            n = int(ph.rsplit("_", 1)[1].rstrip("]"))
        except ValueError:
            n = 0
        contatori[g] = max(contatori.get(g, 0), n)

    # Fase 1: ogni placeholder del documento -> token univoco (niente collisioni).
    doc_map: dict[str, str] = {}
    token_di: dict[str, str] = {}
    for i, ph in enumerate(mappa):
        token_di[ph] = f"\x00{i}\x00"
        testo = testo.replace(ph, token_di[ph])

    # Fase 2: token -> placeholder canonico.
    for ph, reale in mappa.items():
        reale_n = (reale or "").strip()
        canon = inverso.get(reale_n)
        if not canon:
            g = _gruppo(ph)
            contatori[g] = contatori.get(g, 0) + 1
            canon = f"[{g}_{contatori[g]}]"
            registro[canon] = reale_n
            inverso[reale_n] = canon
        testo = testo.replace(token_di[ph], canon)
        doc_map[canon] = reale_n

    lavoro.mappa_entita = registro
    lavoro.save(update_fields=["mappa_entita"])
    return testo, doc_map


@shared_task
def estrai_testo_documento(documento_id: int) -> None:
    """Estrae il testo di un Documento e ne aggiorna lo stato."""
    doc = Documento.objects.get(pk=documento_id)
    doc.stato_estrazione = Documento.StatoEstrazione.IN_CORSO
    doc.errore_estrazione = ""
    doc.save(update_fields=["stato_estrazione", "errore_estrazione"])

    try:
        risultato = estrai_testo(doc.file.path, doc.file.name, get_ocr_backend())
    except Exception as exc:  # noqa: BLE001 - vogliamo registrare qualunque errore
        logger.exception("Estrazione fallita per il documento %s", documento_id)
        doc.stato_estrazione = Documento.StatoEstrazione.ERRORE
        doc.errore_estrazione = str(exc)
        doc.save(update_fields=["stato_estrazione", "errore_estrazione"])
        return

    doc.metodo_estrazione = risultato.metodo
    doc.testo_estratto = risultato.testo
    doc.flag_bassa_confidenza = risultato.flag_bassa_confidenza
    doc.passaggi_incerti = risultato.passaggi_incerti
    doc.stato_estrazione = Documento.StatoEstrazione.COMPLETATO
    doc.save(
        update_fields=[
            "metodo_estrazione",
            "testo_estratto",
            "flag_bassa_confidenza",
            "passaggi_incerti",
            "stato_estrazione",
        ]
    )

    # Vincolo tassativo (§119): subito dopo l'estrazione il documento DEVE essere
    # pseudonimizzato prima di poter essere usato/inviato a qualunque LLM.
    pseudonimizza_documento.delay(documento_id)


@shared_task(bind=True, max_retries=3, default_retry_delay=15)
def pseudonimizza_documento(self, documento_id: int) -> None:
    """Pseudonimizza il testo estratto via Privacy Filter (§95/§119).

    Con retry automatico (resilienza) e placeholder canonici a livello di lavoro.
    """
    doc = Documento.objects.get(pk=documento_id)
    doc.stato_anonimizzazione = Documento.StatoAnonimizzazione.IN_CORSO
    doc.errore_anonimizzazione = ""
    doc.save(update_fields=["stato_anonimizzazione", "errore_anonimizzazione"])

    try:
        risultato = get_anonymization_service().anonymize(doc.testo_estratto)
    except Exception as exc:  # noqa: BLE001
        if self.request.retries < self.max_retries:
            logger.warning(
                "Pseudonimizzazione doc %s fallita, retry %s/%s: %s",
                documento_id, self.request.retries + 1, self.max_retries, exc,
            )
            raise self.retry(exc=exc)
        logger.exception("Pseudonimizzazione definitivamente fallita per %s", documento_id)
        doc.stato_anonimizzazione = Documento.StatoAnonimizzazione.ERRORE
        doc.errore_anonimizzazione = str(exc)
        doc.save(update_fields=["stato_anonimizzazione", "errore_anonimizzazione"])
        return

    # Placeholder canonici a livello di lavoro (sotto lock per evitare race).
    with transaction.atomic():
        lavoro = Lavoro.objects.select_for_update().get(pk=doc.sezione.lavoro_id)
        testo, doc_map = _canonicalizza(
            lavoro, risultato.testo_pseudonimizzato, risultato.mappa_entita
        )

    doc.testo_pseudonimizzato = testo
    doc.mappa_entita = doc_map
    doc.pseudonimizzato = True
    doc.stato_anonimizzazione = Documento.StatoAnonimizzazione.COMPLETATA
    doc.save(
        update_fields=[
            "testo_pseudonimizzato",
            "mappa_entita",
            "pseudonimizzato",
            "stato_anonimizzazione",
        ]
    )
