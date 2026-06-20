"""Servizio di analisi LLM (§6/§7).

Principio guida non negoziabile (§1):
- ciò che è OGGETTIVO lo scrive il sistema (sintesi del fatto, cosa chiedono le parti);
- ciò che richiede DISCERNIMENTO giuridico viene posto come INTERROGATIVO all'umano
  (campo `quesiti_aperti`), mai come conclusione definitiva.

Vincolo privacy (§119): l'analisi gira ESCLUSIVAMENTE sul testo pseudonimizzato dei
documenti accettati. Il testo originale non lascia mai il confine del documento.
"""
from __future__ import annotations

import json
import re

from ai.interfaces import LLMBackend
from apps.casi.models import Documento

# Cap di sicurezza sulla lunghezza del prompt (caratteri di testo documentale).
_MAX_CARATTERI = 16000

_ETICHETTA_SEZIONE = {
    "generici": "DOCUMENTI GENERICI",
    "attore": "FASCICOLO DELL'ATTORE",
    "convenuto": "FASCICOLO DEL CONVENUTO/RICORRENTE",
}

# L'analisi è scomposta in DUE chiamate focalizzate: un modello locale (8B) è molto più
# affidabile con un compito per volta che dovendo produrre fatto + richieste insieme.

PROMPT_IN_FATTO = """Sei un assistente che aiuta un operatore dell'Ufficio per il Processo a redigere una bozza.

COMPITO: scrivi la sezione "IN FATTO" — una narrazione sintetica e OGGETTIVA dei fatti di causa, in prosa.

REGOLE TASSATIVE:
- Scrivi solo ciò che è OGGETTIVO e ricavabile dagli atti. Niente valutazioni o conclusioni giuridiche.
- Usa l'italiano. I dati personali sono già pseudonimizzati (es. [PRIVATE_PERSON_1]): \
mantienili tali e non inventare nomi reali.
{modello}
Restituisci ESCLUSIVAMENTE un oggetto JSON: {{"in_fatto": "..."}}

ATTI DEL FASCICOLO (pseudonimizzati):
{documenti}
"""


def _blocco_modello(lavoro) -> str:
    """Blocco opzionale col modello di redazione fornito dall'operatore."""
    modello = (getattr(lavoro, "modello_testo", "") or "").strip()
    if not modello:
        return ""
    return (
        "\nMODELLO DI REDAZIONE — adotta questa IMPOSTAZIONE (suddivisione in paragrafi) "
        "e questo METODO DI SCRITTURA come riferimento di stile e struttura:\n"
        f"{modello[:4000]}\n"
    )

PROMPT_RICHIESTE = """Sei un assistente che aiuta un operatore dell'Ufficio per il Processo.

COMPITO: estrai TUTTE le domande/conclusioni che ciascuna parte rivolge al giudice.

REGOLE TASSATIVE:
- Elenca SEMPRE almeno la domanda principale di OGNI parte presente nel fascicolo (attore e convenuto).
- La domanda RICONVENZIONALE è SEMPRE del CONVENUTO: usa parte="convenuto". In generale, la \
parte è CHI propone la domanda (in favore di chi è formulata), non chi la subisce.
- NON ripetere la stessa domanda più volte: ogni voce deve essere distinta.
- Riporta in "testo" cosa chiede la parte, in modo OGGETTIVO (es. "chiede la condanna al pagamento di X").
- NON trarre conclusioni giuridiche. Ciò che richiede valutazione o discrezionalità va posto come \
domanda all'operatore nel campo "quesiti_aperti".
- I dati personali sono già pseudonimizzati: mantienili tali.

Restituisci ESCLUSIVAMENTE un oggetto JSON con questa struttura:
{{
  "richieste": [
    {{
      "parte": "attore" | "convenuto",
      "testo": "cosa chiede la parte",
      "quesiti_aperti": ["eventuali domande all'operatore su punti discrezionali"]
    }}
  ]
}}

ATTI DEL FASCICOLO (pseudonimizzati):
{documenti}
"""

# Schema passato a Ollama (format=schema) per VINCOLARE l'output: obbliga la chiave "richieste".
SCHEMA_RICHIESTE = {
    "type": "object",
    "properties": {
        "richieste": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "parte": {"type": "string", "enum": ["attore", "convenuto"]},
                    "testo": {"type": "string"},
                    "quesiti_aperti": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["parte", "testo", "quesiti_aperti"],
            },
        }
    },
    "required": ["richieste"],
}


def documenti_utilizzabili(lavoro):
    """Documenti pseudonimizzati e accettati: gli unici ammessi all'analisi (§123)."""
    return Documento.objects.filter(
        sezione__lavoro=lavoro,
        pseudonimizzato=True,
        stato_accettazione__in=[
            Documento.StatoAccettazione.VERIFICATO,
            Documento.StatoAccettazione.ACCETTATO_SENZA_VERIFICA,
        ],
    ).select_related("sezione")


def _componi_documenti(documenti) -> str:
    blocchi: list[str] = []
    for doc in documenti:
        etichetta = _ETICHETTA_SEZIONE.get(doc.sezione.tipo, doc.sezione.tipo.upper())
        blocchi.append(f"### {etichetta}\n{doc.testo_pseudonimizzato.strip()}")
    testo = "\n\n".join(blocchi)
    return testo[:_MAX_CARATTERI]


def _estrai_json(grezzo: str) -> dict:
    """Estrae l'oggetto JSON dalla risposta del modello in modo robusto."""
    # Rimuove eventuali blocchi di ragionamento dei modelli "thinking".
    grezzo = re.sub(r"<think>.*?</think>", "", grezzo, flags=re.DOTALL).strip()
    try:
        return json.loads(grezzo)
    except json.JSONDecodeError:
        inizio, fine = grezzo.find("{"), grezzo.rfind("}")
        if inizio == -1 or fine == -1:
            raise ValueError("Risposta LLM priva di JSON valido.")
        return json.loads(grezzo[inizio : fine + 1])


PROMPT_IN_DIRITTO = """Sei un assistente che aiuta un operatore dell'Ufficio per il Processo \
nell'analisi "in diritto" di UNA singola richiesta di parte.

REGOLE TASSATIVE (§1/§2):
- Lavora solo sugli atti forniti (pseudonimizzati). Non inventare fatti né documenti.
- L'attribuzione dell'onere probatorio e ogni valutazione di merito NON sono conclusioni \
definitive: proponile e chiedi conferma all'operatore nel campo "quesiti_aperti".
- In "allegati" indica SOLO i documenti effettivamente pertinenti a QUESTA singola richiesta \
(di norma 1-3, quelli che la fondano o la contrastano). NON elencare tutti i documenti del \
fascicolo: se un documento non incide su questa richiesta, omettilo.

RICHIESTA DA ANALIZZARE (parte: {parte}):
{richiesta}

DOCUMENTI DISPONIBILI (pseudonimizzati, con ID):
{documenti}
{riferimenti}
Restituisci ESCLUSIVAMENTE un oggetto JSON:
{{
  "onere_probatorio": "proposta oggettiva su a chi spetta l'onere, da confermare",
  "allegati": [<id dei documenti pertinenti>],
  "non_contestazioni": ["fatti che risultano non contestati"],
  "quesiti_aperti": [
    "domande all'operatore sui punti discrezionali (es. conferma onere, prova della domanda)"
  ]
}}
"""


def _componi_documenti_con_id(documenti) -> str:
    blocchi: list[str] = []
    for doc in documenti:
        etichetta = _ETICHETTA_SEZIONE.get(doc.sezione.tipo, doc.sezione.tipo.upper())
        blocchi.append(
            f"### Documento {doc.id} — {etichetta}\n{doc.testo_pseudonimizzato.strip()}"
        )
    return "\n\n".join(blocchi)[:_MAX_CARATTERI]


def approfondisci_richiesta(
    richiesta, documenti, llm: LLMBackend, riferimenti: str = ""
) -> dict:
    """Ragionamento 'in diritto' su una singola richiesta (M2).

    `documenti` sono i Documenti utilizzabili del lavoro (pseudonimizzati e accettati);
    vengono passati con il loro ID per consentire il collegamento degli allegati.
    `riferimenti` è materiale di approfondimento dal corpus (RAG, §83): spunti da
    valutare, non vincoli — opzionale.
    """
    blocco_rif = (
        f"\nRIFERIMENTI dal corpus (spunti, da valutare):\n{riferimenti}\n"
        if riferimenti
        else ""
    )
    prompt = PROMPT_IN_DIRITTO.format(
        parte=richiesta.parte_richiedente,
        richiesta=richiesta.testo,
        documenti=_componi_documenti_con_id(documenti),
        riferimenti=blocco_rif,
    )
    grezzo = llm.generate(prompt, format="json", think=False, temperature=0.2)
    dati = _estrai_json(grezzo)

    id_validi = {d.id for d in documenti}
    allegati: list[int] = []
    for x in dati.get("allegati", []):
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n in id_validi and n not in allegati:
            allegati.append(n)
    return {
        "onere_probatorio": str(dati.get("onere_probatorio", "")).strip(),
        "allegati": allegati,
        "non_contestazioni": [str(x) for x in dati.get("non_contestazioni", []) if x],
        "quesiti_aperti": [str(x) for x in dati.get("quesiti_aperti", []) if x],
    }


def analizza_lavoro(lavoro, llm: LLMBackend) -> dict:
    """Esegue l'analisi e restituisce il dizionario {in_fatto, richieste}.

    Due chiamate focalizzate (un compito ciascuna): l'"in fatto" e — separatamente —
    l'estrazione delle richieste, vincolata da uno schema JSON. Questo rende l'estrazione
    affidabile anche su fascicoli ampi, dove un modello locale tende a ometterne una.
    """
    documenti = list(documenti_utilizzabili(lavoro))
    if not documenti:
        raise ValueError(
            "Nessun documento utilizzabile: caricane e accettane almeno uno."
        )
    blocco = _componi_documenti(documenti)
    modello = _blocco_modello(lavoro)

    # 1) Sezione "in fatto" (seguendo l'eventuale modello di redazione dell'operatore).
    grezzo_fatto = llm.generate(
        PROMPT_IN_FATTO.format(documenti=blocco, modello=modello),
        format="json",
        think=False,
        temperature=0.2,
    )
    in_fatto = str(_estrai_json(grezzo_fatto).get("in_fatto", "")).strip()

    # 2) Richieste delle parti (output vincolato dallo schema).
    grezzo_ric = llm.generate(
        PROMPT_RICHIESTE.format(documenti=blocco),
        format=SCHEMA_RICHIESTE,
        think=False,
        temperature=0.2,
    )
    dati_ric = _estrai_json(grezzo_ric)

    richieste = []
    visti: set[tuple[str, str]] = set()
    for r in dati_ric.get("richieste", []):
        testo = str(r.get("testo", "")).strip()
        if not testo:
            continue
        parte = str(r.get("parte", "")).lower()
        # "riconvenzional" nel testo → è una domanda del convenuto, a prescindere
        # dall'etichetta del modello (che talvolta sbaglia l'attribuzione).
        if "conven" in parte or "ricorr" in parte or "riconvenzional" in testo.lower():
            parte = "convenuto"
        else:
            parte = "attore"
        chiave = (parte, testo.casefold())
        if chiave in visti:  # dedup di richieste ripetute dal modello
            continue
        visti.add(chiave)
        richieste.append(
            {
                "parte": parte,
                "testo": testo,
                "quesiti_aperti": [str(q) for q in r.get("quesiti_aperti", []) if q],
            }
        )
    return {"in_fatto": in_fatto, "richieste": richieste}
