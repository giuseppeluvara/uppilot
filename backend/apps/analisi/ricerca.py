"""Ricerca giuridica "spunti di approfondimento" (§6).

Filosofia (§1): propone spunti del tipo "Il contesto suggerisce di cercare
giurisprudenza in merito a…", la ricerca web restituisce risultati da valutare,
e l'output sono SUGGERIMENTI che l'utente integra a sua discrezione — mai
citazioni date per buone.

Privacy (§134): la query esce SEMPRE pseudonimizzata verso l'esterno.
"""
from __future__ import annotations

from ai.interfaces import AnonymizationService, LegalSearchProvider, LLMBackend, SuggerimentoRicerca
from .models import Bozza
from .services import _estrai_json

_MAX_RICERCHE = 3

PROMPT_QUERY = """Dato il caso seguente (testo pseudonimizzato), proponi fino a {n} ricerche di \
giurisprudenza/normativa utili ad approfondire i punti di diritto. Le query devono essere \
generiche (concetti giuridici, NON nomi o dati delle parti) e in italiano.

CASO:
{contesto}

Restituisci ESCLUSIVAMENTE un oggetto JSON:
{{"ricerche": [{{"argomento": "tema in breve", "query": "stringa di ricerca generica"}}]}}
"""

PROMPT_SPUNTO = """Sei un assistente di approfondimento giuridico per un Ufficio per il Processo.
A partire dal materiale seguente ({origine_label}), produci uno SPUNTO di approfondimento, \
NON una citazione data per buona. Sii esplicito che sono suggerimenti da verificare.

ARGOMENTO: {argomento}
QUERY (pseudonimizzata): {query}

RISULTATI:
{risultati}

Restituisci ESCLUSIVAMENTE un oggetto JSON:
{{
  "sintesi": "cosa emerge dal materiale, con cautela ({incipit})",
  "suggerimento": "cosa potrebbe integrare l'operatore, a sua discrezione"
}}
"""


def _contesto_caso(lavoro) -> str:
    parti = []
    bozza = Bozza.objects.filter(lavoro=lavoro).first()
    if bozza and bozza.in_fatto:
        parti.append(f"In fatto: {bozza.in_fatto}")
    for r in lavoro.richieste.all():
        parti.append(f"Richiesta ({r.parte_richiedente}): {r.testo}")
    return "\n".join(parti)[:8000]


def proponi_ricerche(lavoro, llm: LLMBackend) -> list[dict]:
    prompt = PROMPT_QUERY.format(n=_MAX_RICERCHE, contesto=_contesto_caso(lavoro))
    dati = _estrai_json(llm.generate(prompt, format="json", think=False, temperature=0.3))
    ricerche = []
    for r in dati.get("ricerche", [])[:_MAX_RICERCHE]:
        query = str(r.get("query", "")).strip()
        if query:
            ricerche.append({"argomento": str(r.get("argomento", "")).strip(), "query": query})
    return ricerche


def pseudonimizza_query(query: str, anon: AnonymizationService) -> str:
    """Garanzia §134: nessun dato reale delle parti esce verso l'esterno."""
    pseudonimizzata = anon.anonymize(query).testo_pseudonimizzato.strip()
    if not pseudonimizzata:
        raise ValueError("Pseudonimizzazione della query non riuscita: ricerca esterna bloccata.")
    return pseudonimizzata


def _formatta_risultati(risultati: list[SuggerimentoRicerca]) -> str:
    if not risultati:
        return "(nessun risultato dalla ricerca web)"
    return "\n".join(f"- {r.titolo}: {r.sintesi} [{r.fonte or ''}]" for r in risultati)


def _normalizza_spunto_manuale(testo: str) -> str:
    sostituzioni = {
        "La ricerca web suggerisce": "Dai risultati incollati emerge",
        "La ricerca suggerisce": "Dai risultati incollati emerge",
        "Dalla ricerca web emerge": "Dai risultati incollati emerge",
        "Dalla ricerca emerge": "Dai risultati incollati emerge",
    }
    for vecchio, nuovo in sostituzioni.items():
        if testo.startswith(vecchio):
            return nuovo + testo[len(vecchio) :]
    return testo


def sintetizza_spunto(
    argomento: str,
    query: str,
    materiale: str,
    llm: LLMBackend,
    *,
    origine: str = "web",
) -> dict:
    manuale = origine == "manuale"
    prompt = PROMPT_SPUNTO.format(
        argomento=argomento,
        query=query if query else "(non applicabile: materiale incollato manualmente)",
        risultati=materiale,
        origine_label="risultati incollati manualmente"
        if manuale
        else "risultati di ricerca web",
        incipit="'Dai risultati incollati emerge…'"
        if manuale
        else "'La ricerca web suggerisce…'",
    )
    dati = _estrai_json(llm.generate(prompt, format="json", think=False, temperature=0.3))
    sintesi = str(dati.get("sintesi", "")).strip()
    if manuale:
        sintesi = _normalizza_spunto_manuale(sintesi)
    return {
        "sintesi": sintesi,
        "suggerimento": str(dati.get("suggerimento", "")).strip(),
    }
