"""Servizio Privacy Filter di UPPilot.

Espone /anonymize: riceve testo, restituisce una versione PSEUDONIMIZZATA
(non anonimizzata) + la mappa delle entità mascherate.

ATTENZIONE: pseudonimizzazione != anonimizzazione. Sotto il GDPR il dato
pseudonimizzato resta dato personale (§124). Questo servizio NON è una garanzia
di conformità.

Modello: openai/privacy-filter (repo UFFICIALE — esiste un fork fake su HF).
"""
from __future__ import annotations

import os
import re
import threading
from functools import lru_cache

from fastapi import FastAPI
from pydantic import BaseModel

MODEL_NAME = os.environ.get("PRIVACY_FILTER_MODEL", "openai/privacy-filter")

app = FastAPI(title="UPPilot Privacy Filter")

# Una sola inferenza alla volta: su CPU più richieste concorrenti vanno in
# contesa sui core (torch) e i tempi esplodono. Serializzando, ogni richiesta
# resta ~1s anche con più documenti caricati insieme.
_INFER_LOCK = threading.Lock()


class AnonymizeRequest(BaseModel):
    text: str


class AnonymizeResponse(BaseModel):
    testo_pseudonimizzato: str
    mappa_entita: dict[str, str]


@lru_cache(maxsize=1)
def get_pipeline():
    """Carica il modello una sola volta (lazy, al primo /anonymize)."""
    from transformers import pipeline

    return pipeline(
        "token-classification",
        model=MODEL_NAME,
        aggregation_strategy="simple",
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "privacy-filter", "model": MODEL_NAME}


# Pattern PII italiani non sempre coperti (o mal etichettati) dal modello.
# Hanno PRIORITÀ sul modello: etichetta corretta + cattura di eventuali PII sfuggite.
_RE_PII = [
    ("CODICE_FISCALE", re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("PARTITA_IVA", re.compile(r"\b\d{11}\b")),
]


def _span_regex(testo: str) -> list[dict]:
    out: list[dict] = []
    for label, rx in _RE_PII:
        for m in rx.finditer(testo):
            out.append({"group": label, "start": m.start(), "end": m.end()})
    return out


def _sovrappongono(a: dict, b: dict) -> bool:
    return a["start"] < b["end"] and b["start"] < a["end"]


def _fondi_span_adiacenti(testo: str, entita: list[dict]) -> list[dict]:
    """Fonde span contigui dello stesso tipo.

    Il modello usa un decoding custom che spesso spezza un'entità (es. nome e
    cognome, o un'email) in più token adiacenti. Li riuniamo quando tra due span
    dello stesso `entity_group` c'è solo spazio, così l'output resta leggibile.
    """
    ordinate = sorted(entita, key=lambda e: e["start"])
    fusi: list[dict] = []
    for ent in ordinate:
        gruppo = ent.get("entity_group", "ENTITA")
        if (
            fusi
            and fusi[-1]["group"] == gruppo
            and testo[fusi[-1]["end"] : ent["start"]].strip() == ""
        ):
            fusi[-1]["end"] = ent["end"]
        else:
            fusi.append({"group": gruppo, "start": ent["start"], "end": ent["end"]})
    return fusi


@app.post("/anonymize", response_model=AnonymizeResponse)
def anonymize(req: AnonymizeRequest) -> AnonymizeResponse:
    nlp = get_pipeline()
    with _INFER_LOCK:
        entita = nlp(req.text)
    span_modello = _fondi_span_adiacenti(req.text, entita)

    # Le regex hanno priorità: scarto gli span del modello che vi si sovrappongono,
    # poi unisco. Risolvo eventuali residue sovrapposizioni tenendo lo span più lungo.
    span_regex = _span_regex(req.text)
    span = [m for m in span_modello if not any(_sovrappongono(m, r) for r in span_regex)]
    span += span_regex
    span.sort(key=lambda s: (s["start"], -(s["end"] - s["start"])))
    finale: list[dict] = []
    for s in span:
        if not any(_sovrappongono(s, f) for f in finale):
            finale.append(s)
    span = finale

    # Numerazione in ordine di lettura.
    mappa: dict[str, str] = {}
    contatori: dict[str, int] = {}
    for s in span:
        gruppo = s["group"].upper()
        contatori[gruppo] = contatori.get(gruppo, 0) + 1
        s["placeholder"] = f"[{gruppo}_{contatori[gruppo]}]"
        mappa[s["placeholder"]] = req.text[s["start"] : s["end"]]

    # Sostituzione dalla fine all'inizio per non spostare gli offset.
    testo = req.text
    for s in sorted(span, key=lambda s: s["start"], reverse=True):
        testo = testo[: s["start"]] + s["placeholder"] + testo[s["end"] :]

    return AnonymizeResponse(testo_pseudonimizzato=testo, mappa_entita=mappa)
