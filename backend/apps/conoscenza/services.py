"""Costruzione del grafo della conoscenza dal corpus (e, in fase 3, dai casi).

Usa il LLM LOCALE su testo pseudonimizzato. L'output è vincolato da uno schema JSON
(come per le richieste in apps/analisi). I nodi sono fusi per chiave normalizzata:
lo stesso concetto, estratto da documenti diversi, diventa un unico nodo — ed è ciò
che rende il grafo connesso.
"""
from __future__ import annotations

import json
import re
import unicodedata

from ai.interfaces import LLMBackend

from .models import Arco, Nodo

_MAX_CARATTERI = 6000

PROMPT_GRAFO = """Sei un assistente giuridico. Dal testo seguente (normativa/giurisprudenza, \
già pseudonimizzato) estrai una piccola MAPPA DI CONOSCENZA.

REGOLE:
- Estrai i CONCETTI/ISTITUTI giuridici principali (tipo "concetto") e i RIFERIMENTI \
normativi citati (tipo "riferimento", es. "Art. 1460 c.c.").
- Per ogni nodo: un'etichetta concisa e una "sintesi" OGGETTIVA di una frase.
- Estrai gli ARCHI (relazioni) tra i nodi usando le loro etichette esatte: "cita", \
"correlato", "in_contrasto", "applica".
- Massimo circa 8 nodi e 10 archi. Niente conclusioni: solo ciò che è nel testo.

Restituisci SOLO un oggetto JSON:
{{"nodi":[{{"tipo":"concetto|riferimento","etichetta":"...","sintesi":"..."}}], \
"archi":[{{"da":"etichetta","a":"etichetta","tipo":"cita|correlato|in_contrasto|applica"}}]}}

TESTO:
{testo}
"""

SCHEMA_GRAFO = {
    "type": "object",
    "properties": {
        "nodi": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": ["concetto", "riferimento"]},
                    "etichetta": {"type": "string"},
                    "sintesi": {"type": "string"},
                },
                "required": ["tipo", "etichetta", "sintesi"],
            },
        },
        "archi": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "da": {"type": "string"},
                    "a": {"type": "string"},
                    "tipo": {
                        "type": "string",
                        "enum": ["cita", "correlato", "in_contrasto", "applica"],
                    },
                },
                "required": ["da", "a", "tipo"],
            },
        },
    },
    "required": ["nodi", "archi"],
}

_TIPI_ARCO = {"cita", "correlato", "in_contrasto", "applica"}


def normalizza_chiave(etichetta: str) -> str:
    """Chiave canonica per la fusione dei nodi (accenti/punteggiatura/maiuscole ininfluenti)."""
    s = unicodedata.normalize("NFKD", etichetta).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return s[:255]


def _estrai_json(grezzo: str) -> dict:
    grezzo = re.sub(r"<think>.*?</think>", "", grezzo, flags=re.DOTALL).strip()
    try:
        return json.loads(grezzo)
    except json.JSONDecodeError:
        inizio, fine = grezzo.find("{"), grezzo.rfind("}")
        if inizio == -1 or fine == -1:
            raise ValueError("Risposta LLM priva di JSON valido.")
        return json.loads(grezzo[inizio : fine + 1])


def upsert_nodo(
    etichetta: str,
    tipo: str = Nodo.Tipo.CONCETTO,
    sintesi: str = "",
    documento=None,
    lavoro=None,
    chiave: str | None = None,
) -> Nodo | None:
    """Crea o recupera un nodo per chiave normalizzata (merge)."""
    etichetta = (etichetta or "").strip()
    if chiave is None:
        chiave = normalizza_chiave(etichetta)
    if not chiave:
        return None
    nodo, creato = Nodo.objects.get_or_create(
        chiave=chiave,
        defaults={
            "tipo": tipo,
            "etichetta": etichetta or chiave,
            "sintesi": (sintesi or "").strip(),
            "documento": documento,
            "lavoro": lavoro,
        },
    )
    # Arricchisce un nodo già esistente se privo di sintesi.
    if not creato and sintesi and not nodo.sintesi:
        nodo.sintesi = sintesi.strip()
        nodo.save(update_fields=["sintesi"])
    return nodo


def materializza(dati: dict, documento=None) -> None:
    """Crea nodi/archi a partire dall'output del modello."""
    mappa: dict[str, Nodo] = {}
    for n in dati.get("nodi", []):
        etichetta = str(n.get("etichetta", "")).strip()
        if not etichetta:
            continue
        tipo = "riferimento" if str(n.get("tipo")) == "riferimento" else "concetto"
        nodo = upsert_nodo(etichetta, tipo, str(n.get("sintesi", "")), documento=documento)
        if nodo:
            mappa[normalizza_chiave(etichetta)] = nodo

    for a in dati.get("archi", []):
        da_lbl = str(a.get("da", "")).strip()
        a_lbl = str(a.get("a", "")).strip()
        if not da_lbl or not a_lbl:
            continue
        da = mappa.get(normalizza_chiave(da_lbl)) or upsert_nodo(da_lbl, documento=documento)
        ad = mappa.get(normalizza_chiave(a_lbl)) or upsert_nodo(a_lbl, documento=documento)
        if not da or not ad or da.id == ad.id:
            continue
        tipo = str(a.get("tipo", "correlato"))
        tipo = tipo if tipo in _TIPI_ARCO else "correlato"
        Arco.objects.get_or_create(da=da, a=ad, tipo=tipo)


def estrai_grafo_corpus(documento, llm: LLMBackend) -> None:
    """Estrae nodi/archi da un documento del corpus e li fonde nel grafo."""
    grezzo = llm.generate(
        PROMPT_GRAFO.format(testo=documento.testo[:_MAX_CARATTERI]),
        format=SCHEMA_GRAFO,
        think=False,
        temperature=0.2,
    )
    materializza(_estrai_json(grezzo), documento=documento)
