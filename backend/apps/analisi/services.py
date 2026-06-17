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

PROMPT = """Sei un assistente che aiuta un operatore dell'Ufficio per il Processo a redigere una bozza.

REGOLE TASSATIVE:
- Scrivi solo ciò che è OGGETTIVO e ricavabile dagli atti.
- NON trarre conclusioni giuridiche definitive. Ogni punto che richiede valutazione o \
discrezionalità va formulato come domanda all'operatore nel campo "quesiti_aperti".
- Usa l'italiano. I dati personali sono già pseudonimizzati (es. [PRIVATE_PERSON_1]): \
mantienili tali e non inventare nomi reali.

Restituisci ESCLUSIVAMENTE un oggetto JSON con questa struttura:
{{
  "in_fatto": "narrazione sintetica e oggettiva del fatto, in prosa",
  "richieste": [
    {{
      "parte": "attore" | "convenuto",
      "testo": "cosa chiede la parte, in modo oggettivo",
      "quesiti_aperti": ["eventuali domande all'operatore su punti discrezionali"]
    }}
  ]
}}

ATTI DEL FASCICOLO (pseudonimizzati):
{documenti}
"""


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
    """Esegue l'analisi e restituisce il dizionario {in_fatto, richieste}."""
    documenti = list(documenti_utilizzabili(lavoro))
    if not documenti:
        raise ValueError(
            "Nessun documento utilizzabile: caricane e accettane almeno uno."
        )

    prompt = PROMPT.format(documenti=_componi_documenti(documenti))
    grezzo = llm.generate(prompt, format="json", think=False, temperature=0.2)
    dati = _estrai_json(grezzo)

    # Normalizzazione difensiva dell'output del modello.
    dati.setdefault("in_fatto", "")
    richieste = []
    for r in dati.get("richieste", []):
        parte = str(r.get("parte", "")).lower()
        parte = "convenuto" if "conven" in parte or "ricorr" in parte else "attore"
        richieste.append(
            {
                "parte": parte,
                "testo": str(r.get("testo", "")).strip(),
                "quesiti_aperti": [str(q) for q in r.get("quesiti_aperti", []) if q],
            }
        )
    dati["richieste"] = richieste
    return dati
