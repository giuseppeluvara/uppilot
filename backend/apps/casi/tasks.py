"""Task asincroni dell'app casi (§82): OCR/estrazione fuori dal ciclo richiesta."""
from __future__ import annotations

import logging
import re

from celery import shared_task
from django.db import transaction

from ai.factory import get_anonymization_service, get_ocr_backend

from .models import Documento, Lavoro
from .privacy import (
    candidati_pii_sconosciuti,
    gruppo_placeholder,
    maschera_residui,
    normalizza_entita,
    normalizza_spazi_placeholder,
    PLACEHOLDER_RE,
)
from .services.extraction import estrai_testo

logger = logging.getLogger(__name__)

_RE_GRUPPO = re.compile(r"\[(.+)_\d+\]")
_FUZZY_GROUPS = {"ORG", "ORGANIZATION", "PERSON", "PRIVATE_PERSON"}
_ORG_CUES = {
    "associazione",
    "azienda",
    "condominio",
    "cooperativa",
    "ditta",
    "ente",
    "fondazione",
    "impresa",
    "istituto",
    "societa",
    "srl",
    "spa",
    "snc",
    "sas",
}
_ADDRESS_PREFIX_STOP = {"via", "viale", "piazza", "corso", "largo"}


def _gruppo(placeholder: str) -> str:
    """Estrae il gruppo da un placeholder, es. '[PRIVATE_PERSON_3]' -> 'PRIVATE_PERSON'."""
    m = _RE_GRUPPO.match(placeholder)
    return m.group(1) if m else "ENTITA"


def _pulisci_valore_entita(valore: str) -> str:
    """Ripulisce valori spurii del privacy-filter, spesso preceduti da intestazioni."""
    righe = [r.strip(" \t:-") for r in (valore or "").splitlines() if r.strip()]
    if righe:
        valore = righe[-1]
    valore = re.sub(r"\s+", " ", valore or "").strip()
    return valore


def _contatori_da_registro(registro: dict[str, str]) -> dict[str, int]:
    contatori: dict[str, int] = {}
    for ph in registro:
        g = _gruppo(ph)
        try:
            n = int(ph.rsplit("_", 1)[1].rstrip("]"))
        except ValueError:
            n = 0
        contatori[g] = max(contatori.get(g, 0), n)
    return contatori


def _nuovo_placeholder(registro: dict[str, str], gruppo: str) -> str:
    contatori = _contatori_da_registro(registro)
    contatori[gruppo] = contatori.get(gruppo, 0) + 1
    ph = f"[{gruppo}_{contatori[gruppo]}]"
    while ph in registro:
        contatori[gruppo] += 1
        ph = f"[{gruppo}_{contatori[gruppo]}]"
    return ph


def _gia_in_registro(valore: str, registro: dict[str, str]) -> bool:
    norm = normalizza_entita(valore)
    if not norm:
        return True
    for reale in registro.values():
        n_reale = normalizza_entita(reale)
        if norm == n_reale or norm in n_reale or n_reale in norm:
            return True
    return False


def _placeholder_in_registro(valore: str, registro: dict[str, str]) -> str | None:
    norm = normalizza_entita(valore)
    if not norm:
        return None
    for ph, reale in registro.items():
        n_reale = normalizza_entita(reale)
        if norm == n_reale or norm in n_reale or n_reale in norm:
            return ph
    return None


def _gruppo_candidato(candidato: dict[str, str]) -> str:
    tipo = candidato.get("tipo", "")
    token = candidato.get("token", "")
    parole = set(normalizza_entita(token).split())
    if tipo == "persona":
        return "PRIVATE_PERSON"
    if tipo == "organizzazione" or parole & _ORG_CUES:
        return "ORGANIZZAZIONE"
    return "PRIVATE_PERSON"


def _ripara_frammenti_troncati(
    testo: str, registro: dict[str, str], doc_map: dict[str, str]
) -> str:
    """Ricompone alcuni tagli tipici del privacy filter su date e indirizzi."""
    for ph, reale in list(registro.items()):
        gruppo = gruppo_placeholder(ph) or _gruppo(ph)
        if "DATE" in gruppo and re.search(r"\b(?:19|20)\d$", reale or ""):
            pattern = re.compile(rf"{re.escape(ph)}\s*(\d)\b")

            def repl_date(match: re.Match[str]) -> str:
                registro[ph] = f"{registro[ph]}{match.group(1)}"
                doc_map[ph] = registro[ph]
                return ph

            testo = pattern.sub(repl_date, testo, count=1)
        elif "DATE" in gruppo and re.search(r"\b(?:19|20)\d{2}$", reale or ""):
            ultima_cifra = re.escape((reale or "")[-1])
            testo = re.sub(rf"{re.escape(ph)}\s*{ultima_cifra}\b", ph, testo, count=1)

        if "ADDRESS" in gruppo and reale and len(reale) <= 32:
            pattern = re.compile(
                rf"\b([A-ZÀ-Ö][a-zà-öø-ÿ]{{2,12}})\s*{re.escape(ph)}"
            )

            def repl_address(match: re.Match[str]) -> str:
                prefisso = match.group(1)
                if normalizza_entita(prefisso) in _ADDRESS_PREFIX_STOP:
                    return match.group(0)
                if registro[ph][:1].islower():
                    registro[ph] = f"{prefisso}{registro[ph]}".strip()
                doc_map[ph] = registro[ph]
                return ph

            testo = pattern.sub(repl_address, testo, count=1)
    return testo


def _maschera_candidati_sconosciuti(
    testo: str, registro: dict[str, str], doc_map: dict[str, str]
) -> str:
    candidati = sorted(
        candidati_pii_sconosciuti(testo, registro),
        key=lambda c: len(c.get("token", "")),
        reverse=True,
    )
    for candidato in candidati:
        token = _pulisci_valore_entita(candidato.get("token", ""))
        if len(normalizza_entita(token)) < 4:
            continue
        ph_esistente = _placeholder_in_registro(token, registro)
        if ph_esistente:
            doc_map[ph_esistente] = registro[ph_esistente]
            continue
        gruppo = _gruppo_candidato(candidato)
        ph = _nuovo_placeholder(registro, gruppo)
        registro[ph] = token
        doc_map[ph] = token
    return maschera_residui(testo, registro)


def _token_match(norm: str, norm_esistente: str, gruppo: str) -> bool:
    if gruppo not in _FUZZY_GROUPS:
        return False
    tokens = {t for t in norm.split() if not t.isdecimal()}
    tokens_esistenti = {t for t in norm_esistente.split() if not t.isdecimal()}
    if not tokens or not tokens_esistenti:
        return False
    if gruppo in {"ORG", "ORGANIZATION"} and (norm in norm_esistente or norm_esistente in norm):
        return True
    inter = tokens & tokens_esistenti
    base = min(len(tokens), len(tokens_esistenti))
    # Match fuzzy solo con sovrapposizione forte. Per persone evita di unire due
    # soggetti diversi sul solo cognome; per organizzazioni consente varianti di
    # ragione sociale già normalizzate (es. "Alfa" vs "Alfa Costruzioni").
    if gruppo in {"PERSON", "PRIVATE_PERSON"}:
        return base >= 2 and len(inter) / base >= 0.8
    return len(inter) / base >= 0.75


def _canonicalizza(lavoro: Lavoro, testo: str, mappa: dict) -> tuple[str, dict]:
    """Rimappa i placeholder del documento su placeholder CANONICI a livello di lavoro.

    Stessa entità reale -> stesso placeholder in tutti i documenti del lavoro.
    Aggiorna `lavoro.mappa_entita` (placeholder canonico -> valore reale). Va eseguito
    sotto select_for_update per evitare race tra documenti pseudonimizzati in parallelo.
    """
    registro = dict(lavoro.mappa_entita)  # canonico -> reale
    inverso = {v: k for k, v in registro.items()}
    inverso_norm: dict[str, dict[str, str]] = {}
    for k, v in registro.items():
        norm = normalizza_entita(v)
        if norm:
            inverso_norm.setdefault(gruppo_placeholder(k) or _gruppo(k), {})[norm] = k
    contatori = _contatori_da_registro(registro)

    # Fase 1: ogni placeholder del documento -> token univoco (niente collisioni).
    doc_map: dict[str, str] = {}
    token_di: dict[str, str] = {}
    for i, ph in enumerate(mappa):
        token_di[ph] = f"\x00{i}\x00"
        testo = testo.replace(ph, token_di[ph])

    def trova_canonico(reale: str, gruppo: str) -> str | None:
        norm = normalizza_entita(reale)
        if not norm:
            return None
        norm_per_gruppo = inverso_norm.get(gruppo, {})
        if norm in norm_per_gruppo:
            return norm_per_gruppo[norm]
        for norm_esistente, canonico in norm_per_gruppo.items():
            if not norm_esistente:
                continue
            if gruppo in {"PRIVATE_ADDRESS", "ADDRESS"} and (
                norm_esistente.endswith(norm) or norm.endswith(norm_esistente)
            ):
                return canonico
            if gruppo in {"PRIVATE_DATE", "DATE"} and (
                norm_esistente.startswith(norm) or norm.startswith(norm_esistente)
            ):
                return canonico
            if _token_match(norm, norm_esistente, gruppo):
                return canonico
        return None

    # Fase 2: token -> placeholder canonico.
    for ph, reale in mappa.items():
        reale_n = _pulisci_valore_entita(reale or "")
        g = _gruppo(ph)
        canon = inverso.get(reale_n) or trova_canonico(reale_n, g)
        if not canon:
            contatori[g] = contatori.get(g, 0) + 1
            canon = f"[{g}_{contatori[g]}]"
            registro[canon] = reale_n
            inverso[reale_n] = canon
            norm = normalizza_entita(reale_n)
            if norm:
                inverso_norm.setdefault(g, {})[norm] = canon
        testo = testo.replace(token_di[ph], canon)
        doc_map[canon] = registro.get(canon, reale_n)

    testo = _ripara_frammenti_troncati(testo, registro, doc_map)
    testo = _maschera_candidati_sconosciuti(testo, registro, doc_map)
    testo = normalizza_spazi_placeholder(maschera_residui(testo, registro))
    for ph in PLACEHOLDER_RE.findall(testo):
        if ph in registro:
            doc_map.setdefault(ph, registro[ph])
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
