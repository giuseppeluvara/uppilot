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
- Ordina i fatti in sequenza processuale naturale: prima attore/ricorrente, poi convenuto/resistente, poi eventi successivi.
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
- NON fondere voci diverse: rigetto della domanda attorea, eccezioni/difese, domanda riconvenzionale e istanze istruttorie sono voci separate.
- La domanda RICONVENZIONALE è SEMPRE del CONVENUTO: usa parte="convenuto". In generale, la \
parte è CHI propone la domanda (in favore di chi è formulata), non chi la subisce.
- Classifica ogni voce con tipo:
  * "domanda" = domanda principale o subordinata della parte;
  * "difesa_eccezione" = rigetto, eccezioni, contestazioni, inammissibilità/improcedibilità;
  * "riconvenzionale" = domanda riconvenzionale del convenuto;
  * "istruttoria" = richiesta di CTU, prove testimoniali, ordine di esibizione o simili;
  * "altro" = solo se nessuna categoria è appropriata.
- NON ripetere la stessa domanda più volte: ogni voce deve essere distinta.
- Riporta in "testo" cosa chiede la parte, in modo OGGETTIVO (es. "chiede la condanna al pagamento di X").
- Mantieni importi, date, numeri di fattura e riferimenti testuali ESATTAMENTE come negli atti.
- NON trarre conclusioni giuridiche. Ciò che richiede valutazione o discrezionalità va posto come \
domanda all'operatore nel campo "quesiti_aperti".
- I dati personali sono già pseudonimizzati: mantienili tali.

Restituisci ESCLUSIVAMENTE un oggetto JSON con questa struttura:
{{
  "richieste": [
    {{
      "parte": "attore" | "convenuto",
      "tipo": "domanda" | "difesa_eccezione" | "riconvenzionale" | "istruttoria" | "altro",
      "testo": "cosa chiede la parte",
      "confidence": 0.0,
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
                    "tipo": {
                        "type": "string",
                        "enum": [
                            "domanda",
                            "difesa_eccezione",
                            "riconvenzionale",
                            "istruttoria",
                            "altro",
                        ],
                    },
                    "testo": {"type": "string"},
                    "confidence": {"type": "number"},
                    "quesiti_aperti": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["parte", "tipo", "testo", "confidence", "quesiti_aperti"],
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


def _in_fatto_da_grezzo(grezzo: str) -> str:
    """Estrae l'in-fatto in modo RESILIENTE: salva il testo anche da JSON troncato.

    Il modello locale (8B) a volte produce JSON malformato/troncato ("Unterminated
    string"): in quel caso, anziché far fallire tutta l'analisi, recuperiamo il
    valore di "in_fatto" col regex.
    """
    grezzo = re.sub(r"<think>.*?</think>", "", grezzo, flags=re.DOTALL).strip()
    try:
        return str(_estrai_json(grezzo).get("in_fatto", "")).strip()
    except (ValueError, json.JSONDecodeError):
        pass
    m = re.search(r'"in_fatto"\s*:\s*"(.*)', grezzo, flags=re.DOTALL)
    if not m:
        return ""
    val = m.group(1)
    # Taglia un'eventuale coda JSON e gli apici, poi de-escape minimale.
    val = re.sub(r'"\s*}\s*$', "", val.strip()).rstrip().rstrip('"')
    return val.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t").strip()


PROMPT_IN_DIRITTO = """Sei un assistente che aiuta un operatore dell'Ufficio per il Processo \
nell'analisi "in diritto" di UNA singola richiesta di parte.

REGOLE TASSATIVE (§1/§2):
- Lavora solo sugli atti forniti (pseudonimizzati). Non inventare fatti né documenti.
- L'attribuzione dell'onere probatorio e ogni valutazione di merito NON sono conclusioni \
definitive: proponile e chiedi conferma all'operatore nel campo "quesiti_aperti".
- In "allegati" indica SOLO i documenti effettivamente pertinenti a QUESTA singola richiesta \
(di norma 1-3, quelli che la fondano o la contrastano). NON elencare tutti i documenti del \
fascicolo: se un documento non incide su questa richiesta, omettilo.
- In "non_contestazioni" inserisci SOLO fatti espressamente indicati come non contestati/pacifici \
oppure ammessi da entrambe le parti. Se il fatto è solo allegato da una parte, lascialo fuori e \
poni un quesito aperto.
- Mantieni importi, date e numeri identificativi ESATTAMENTE come nella richiesta e nei documenti.

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


_STOP_RILEVANZA = {
    "chiede",
    "domanda",
    "parte",
    "attore",
    "convenuto",
    "condanna",
    "pagamento",
    "rigetto",
    "accertare",
    "contratto",
    "euro",
}


def _token_rilevanti(testo: str) -> set[str]:
    out = set()
    for token in re.findall(r"[\wÀ-ÖØ-öø-ÿ']+", testo.casefold()):
        if len(token) < 4 or token.isdecimal() or token in _STOP_RILEVANZA:
            continue
        out.add(token)
    return out


def _filtra_allegati_pertinenti(richiesta, documenti, allegati: list[int]) -> list[int]:
    """Riduce l'effetto "tutti gli allegati" usando overlap lessicale minimale."""
    if not allegati:
        return []
    tokens = _token_rilevanti(richiesta.testo)
    if not tokens:
        return allegati[:3]
    per_id = {d.id: d for d in documenti}
    scored: list[tuple[int, int]] = []
    for doc_id in allegati:
        doc = per_id.get(doc_id)
        if not doc:
            continue
        score = len(tokens & _token_rilevanti(doc.testo_pseudonimizzato))
        if score > 0:
            scored.append((score, doc_id))
    scored.sort(reverse=True)
    if not scored:
        return [doc_id for doc_id in allegati if doc_id in per_id][:1]
    return [doc_id for _, doc_id in scored[:3]]


def _non_contestazione_affidabile(testo: str) -> bool:
    basso = testo.casefold()
    indicatori = ("non contest", "pacific", "concord", "ammess", "riconosciut")
    return any(x in basso for x in indicatori)


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
    non_contestate: list[str] = []
    quesiti = [str(x) for x in dati.get("quesiti_aperti", []) if x]
    for voce in [str(x) for x in dati.get("non_contestazioni", []) if x]:
        if _non_contestazione_affidabile(voce):
            non_contestate.append(voce)
        else:
            quesiti.append(f"Verifica se il fatto è davvero non contestato: {voce}")

    return {
        "onere_probatorio": str(dati.get("onere_probatorio", "")).strip(),
        "allegati": _filtra_allegati_pertinenti(richiesta, documenti, allegati),
        "non_contestazioni": non_contestate,
        "quesiti_aperti": quesiti,
    }


def classifica_tipo_richiesta(testo: str, parte: str) -> str:
    basso = testo.casefold()
    if "riconvenzional" in basso:
        return "riconvenzionale"
    if any(x in basso for x in ("ctu", "testimon", "prova", "esibizion", "interrogatorio")):
        return "istruttoria"
    if any(x in basso for x in ("rigett", "eccepis", "inammiss", "improced", "resping")):
        return "difesa_eccezione"
    return "domanda"


def _confidence(valore) -> float:
    try:
        return max(0.0, min(1.0, float(valore)))
    except (TypeError, ValueError):
        return 0.65


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
    in_fatto = _in_fatto_da_grezzo(grezzo_fatto)

    # 2) Richieste delle parti (output vincolato dallo schema). Resiliente: un JSON
    # malformato del modello locale non deve far fallire l'intera analisi.
    grezzo_ric = llm.generate(
        PROMPT_RICHIESTE.format(documenti=blocco),
        format=SCHEMA_RICHIESTE,
        think=False,
        temperature=0.2,
    )
    try:
        dati_ric = _estrai_json(grezzo_ric)
    except (ValueError, json.JSONDecodeError):
        dati_ric = {"richieste": []}

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
        tipo = str(r.get("tipo") or classifica_tipo_richiesta(testo, parte))
        if tipo not in {"domanda", "difesa_eccezione", "riconvenzionale", "istruttoria", "altro"}:
            tipo = classifica_tipo_richiesta(testo, parte)
        if tipo == "riconvenzionale":
            parte = "convenuto"
        chiave = (parte, testo.casefold())
        if chiave in visti:  # dedup di richieste ripetute dal modello
            continue
        visti.add(chiave)
        flags = []
        if "rigett" in testo.casefold() and "riconvenzional" in testo.casefold():
            flags.append(
                "La voce sembra unire difesa/eccezione e domanda riconvenzionale: valuta di separarla."
            )
        richieste.append(
            {
                "parte": parte,
                "tipo": tipo,
                "testo": testo,
                "confidence": _confidence(r.get("confidence")),
                "flags": flags,
                "quesiti_aperti": [str(q) for q in r.get("quesiti_aperti", []) if q],
            }
        )
    return {"in_fatto": in_fatto, "richieste": richieste}
