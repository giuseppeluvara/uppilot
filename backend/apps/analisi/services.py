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
from collections.abc import Callable
from difflib import SequenceMatcher

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
- Estrai anche le domande di mero accertamento (es. accertare l'adempimento) anche se accanto a una condanna.
- NON fondere voci diverse: rigetto della domanda attorea, eccezioni/difese, domanda riconvenzionale e istanze istruttorie sono voci separate.
- La richiesta di applicare una penale contrattuale NON è istruttoria: è una domanda sostanziale.
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
- Compila sempre "motivazione": deve essere una bozza prudente e revisionabile, non una decisione definitiva.
- L'attribuzione dell'onere probatorio e ogni valutazione di merito NON sono conclusioni \
definitive: proponile e chiedi conferma all'operatore nel campo "quesiti_aperti".
- Se la richiesta riguarda una penale per ritardo, non invertire l'onere: chi invoca la \
penale deve provare clausola, ritardo, durata, imputabilità alla controparte e calcolo; \
la controparte può provare fatti impeditivi o cause non imputabili.
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
  "motivazione": "bozza sintetica e prudente della motivazione sul capo, con punti da verificare",
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

_NUMERO_SENSIBILE_RE = re.compile(
    r"(?:€\s*)?\b\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?\b|\b\d+/\d{2,4}\b|"
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    re.IGNORECASE,
)


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


def _non_contestazione_supportata(testo: str, documenti) -> bool:
    """Accetta solo non-contestazioni prudenti, evitando fatti solo allegati."""
    if not _non_contestazione_affidabile(testo):
        return False
    corpus = "\n".join(d.testo_pseudonimizzato for d in documenti).casefold()
    indicatori_testuali = ("non contest", "pacific", "concord", "ammess", "riconosciut")
    if any(ind in corpus for ind in indicatori_testuali):
        return True

    # Fallback molto stretto: nei fascicoli civili l'esistenza del contratto/appalto
    # può risultare comune se compare sia negli atti dell'attore sia in quelli del convenuto.
    basso = testo.casefold()
    if not any(x in basso for x in ("contratto", "appalto")):
        return False
    if not any(x in basso for x in ("esistenza", "stipula", "sottoscrizione")):
        return False
    sezioni = {
        d.sezione.tipo
        for d in documenti
        if any(x in (d.testo_pseudonimizzato or "").casefold() for x in ("contratto", "appalto"))
    }
    return "attore" in sezioni and "convenuto" in sezioni


def _motivazione_fallback(richiesta, onere: str, quesiti: list[str]) -> str:
    tipo = getattr(richiesta, "tipo", "") or classifica_tipo_richiesta(
        richiesta.testo, richiesta.parte_richiedente
    )
    testo = richiesta.testo.strip()
    base = f"La richiesta di parte {richiesta.parte_richiedente} riguarda: {testo}."
    if tipo == "istruttoria":
        base += (
            " La valutazione deve concentrarsi su rilevanza, ammissibilita' e utilita' "
            "del mezzo istruttorio rispetto ai fatti controversi."
        )
    elif tipo == "difesa_eccezione":
        base += (
            " La decisione richiede di verificare se le contestazioni e le eccezioni "
            "risultano specifiche e supportate dagli atti."
        )
    else:
        base += (
            " La decisione richiede di verificare prova del fatto costitutivo, eventuali "
            "fatti impeditivi o estintivi e coerenza degli importi indicati."
        )
    if onere:
        base += f" {onere}"
    if quesiti:
        base += " Restano da sciogliere i quesiti aperti indicati nella scheda."
    return base.strip()


def _numeri_sensibili(testo: str) -> set[str]:
    return {
        re.sub(r"\s+", "", m.group(0).replace("€", ""))
        for m in _NUMERO_SENSIBILE_RE.finditer(testo or "")
    }


def _label_parte(parte: str) -> str:
    return "convenuto" if parte == "convenuto" else "attore"


def _onere_probatorio_fallback(richiesta) -> str:
    tipo = getattr(richiesta, "tipo", "") or classifica_tipo_richiesta(
        richiesta.testo, richiesta.parte_richiedente
    )
    parte = _label_parte(richiesta.parte_richiedente)
    controparte = "attore" if parte == "convenuto" else "convenuto"
    if tipo == "istruttoria":
        return (
            f"Alla parte {parte} che chiede il mezzo istruttorio spetta indicare i fatti "
            "controversi da provare e la pertinenza del mezzo; restano da valutare "
            "ammissibilita', rilevanza e non esplorativita' rispetto al thema decidendum."
        )
    if tipo == "difesa_eccezione":
        return (
            f"Alla parte {parte} che solleva la difesa o eccezione spetta allegare e provare "
            "i fatti impeditivi, modificativi o estintivi posti a fondamento; alla "
            f"controparte {controparte} resta l'onere sui fatti costitutivi della domanda."
        )
    if tipo == "riconvenzionale":
        return (
            f"Alla parte {parte} che propone la domanda riconvenzionale spetta provare i "
            "fatti costitutivi della pretesa, il nesso con l'inadempimento allegato e la "
            "quantificazione richiesta; alla controparte spettano eventuali fatti "
            "impeditivi, modificativi o estintivi."
        )
    return (
        f"Alla parte {parte} che propone la domanda spetta provare i fatti costitutivi "
        f"della pretesa; alla controparte {controparte} spettano eventuali fatti "
        "impeditivi, modificativi o estintivi."
    )


def _onere_probatorio_guardrail(richiesta, onere: str) -> str:
    """Corregge formulazioni LLM che invertono oneri tipici e ripetitivi."""
    testo = (richiesta.testo or "").casefold()
    onere_basso = (onere or "").casefold()
    if not onere:
        return _onere_probatorio_fallback(richiesta)
    if "penale" in testo and "ritard" in testo:
        errata_non_imputabilita = "non imputabil" in onere_basso and "controparte" not in onere_basso
        incompleto = not all(x in onere_basso for x in ("penale", "ritard"))
        if errata_non_imputabilita or incompleto:
            return (
                "Alla parte che invoca la penale spetta provare esistenza ed efficacia "
                "della clausola penale, ritardo, durata del ritardo, imputabilita' del "
                "ritardo alla controparte e correttezza del calcolo; la controparte puo' "
                "provare fatti impeditivi o cause non imputabili."
            )
    numeri_estranei = _numeri_sensibili(onere) - _numeri_sensibili(richiesta.testo)
    tema_penale_estraneo = "penale" in onere_basso and "penale" not in testo
    tema_ritardo_estraneo = "ritard" in onere_basso and "ritard" not in testo
    tema_fattura_estraneo = "fattur" in onere_basso and "fattur" not in testo
    if (
        numeri_estranei
        or tema_penale_estraneo
        or tema_ritardo_estraneo
        or tema_fattura_estraneo
    ):
        return _onere_probatorio_fallback(richiesta)
    if getattr(richiesta, "tipo", "") == "istruttoria" and not any(
        x in onere_basso for x in ("ammiss", "rilevan", "pertinen", "necess")
    ):
        return _onere_probatorio_fallback(richiesta)
    return onere


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
        if _non_contestazione_supportata(voce, documenti):
            non_contestate.append(voce)
        else:
            quesiti.append(f"Verifica se il fatto è davvero non contestato: {voce}")
    onere = _onere_probatorio_guardrail(
        richiesta, str(dati.get("onere_probatorio", "")).strip()
    )
    motivazione = str(dati.get("motivazione", "")).strip()
    if not motivazione:
        motivazione = _motivazione_fallback(richiesta, onere, quesiti)

    return {
        "onere_probatorio": onere,
        "motivazione": motivazione,
        "allegati": _filtra_allegati_pertinenti(richiesta, documenti, allegati),
        "non_contestazioni": non_contestate,
        "quesiti_aperti": quesiti,
    }


def classifica_tipo_richiesta(testo: str, parte: str) -> str:
    basso = testo.casefold()
    if "riconvenzional" in basso:
        return "riconvenzionale"
    if any(x in basso for x in ("rigett", "eccepis", "eccezion", "contest", "inammiss", "improced", "resping")):
        return "difesa_eccezione"
    if parte == "convenuto" and any(
        x in basso for x in ("condann", "risarc", "costi di ripristino", "ripristino")
    ):
        return "riconvenzionale"
    if any(x in basso for x in ("penale", "condann", "pagamento", "risarc", "accert", "applicare")):
        return "domanda"
    if any(x in basso for x in ("ctu", "testimon", "prova", "esibizion", "interrogatorio")):
        return "istruttoria"
    return "domanda"


def _confidence(valore) -> float:
    try:
        return max(0.0, min(1.0, float(valore)))
    except (TypeError, ValueError):
        return 0.65


def _normalizza_richiesta_testo(testo: str) -> str:
    testo = re.sub(r"\[[A-Z_]+_\d+\]", " ", testo or "")
    testo = re.sub(r"[^\wÀ-ÖØ-öø-ÿ]+", " ", testo.casefold())
    return re.sub(r"\s+", " ", testo).strip()


def _richiesta_simile(a: str, b: str) -> bool:
    na, nb = _normalizza_richiesta_testo(a), _normalizza_richiesta_testo(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    ta, tb = set(na.split()), set(nb.split())
    if ta and tb and len(ta & tb) / max(len(ta | tb), 1) >= 0.72:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.82


_CONCLUSIONI_RE = re.compile(
    r"conclusioni\s+(?:dell['’]attrice|dell['’]attore|attrice|attore|del\s+convenuto|convenuto)"
    r"\s*:\s*(.*?)(?=\n\s*###|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _split_voci_conclusioni(blocco: str) -> list[str]:
    voci: list[str] = []
    matches = list(re.finditer(r"(?m)^\s*(\d+)[.)]\s+", blocco))
    if not matches:
        return []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(blocco)
        voce = blocco[start:end].strip()
        voce = re.sub(r"\s+", " ", voce).strip(" ;.")
        if voce:
            voci.append(voce)
    return voci


def _estrai_conclusioni_heuristiche(documenti) -> list[dict]:
    richieste: list[dict] = []
    for doc in documenti:
        testo = doc.testo_pseudonimizzato or ""
        parte_default = "convenuto" if doc.sezione.tipo == "convenuto" else "attore"
        for match in _CONCLUSIONI_RE.finditer(testo):
            intestazione = match.group(0).split(":", 1)[0].casefold()
            parte = "convenuto" if "convenuto" in intestazione else parte_default
            for voce in _split_voci_conclusioni(match.group(1)):
                tipo = classifica_tipo_richiesta(voce, parte)
                if tipo == "riconvenzionale":
                    parte = "convenuto"
                richieste.append(
                    {
                        "parte": parte,
                        "tipo": tipo,
                        "testo": voce,
                        "confidence": 0.9,
                        "flags": [],
                        "quesiti_aperti": [],
                    }
                )
    return richieste


def analizza_lavoro(
    lavoro,
    llm: LLMBackend,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> dict:
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
    if progress_callback:
        progress_callback("in_fatto", 1, 4, "Redazione della sezione in fatto")
    grezzo_fatto = llm.generate(
        PROMPT_IN_FATTO.format(documenti=blocco, modello=modello),
        format="json",
        think=False,
        temperature=0.2,
    )
    in_fatto = _in_fatto_da_grezzo(grezzo_fatto)

    # 2) Richieste delle parti (output vincolato dallo schema). Resiliente: un JSON
    # malformato del modello locale non deve far fallire l'intera analisi.
    if progress_callback:
        progress_callback("richieste", 2, 4, "Estrazione strutturata delle conclusioni")
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
    def aggiungi_richiesta(r: dict, *, da_heuristica: bool = False) -> None:
        testo = str(r.get("testo", "")).strip()
        if not testo:
            return
        parte = str(r.get("parte", "")).lower()
        # "riconvenzional" nel testo → è una domanda del convenuto, a prescindere
        # dall'etichetta del modello (che talvolta sbaglia l'attribuzione).
        if "conven" in parte or "ricorr" in parte or "riconvenzional" in testo.lower():
            parte = "convenuto"
        else:
            parte = "attore"
        tipo = classifica_tipo_richiesta(testo, parte)
        if tipo not in {"domanda", "difesa_eccezione", "riconvenzionale", "istruttoria", "altro"}:
            tipo = classifica_tipo_richiesta(testo, parte)
        if tipo == "riconvenzionale":
            parte = "convenuto"
        if any(_richiesta_simile(testo, esistente["testo"]) and parte == esistente["parte"] for esistente in richieste):
            return
        chiave = (parte, testo.casefold())
        if chiave in visti:  # dedup di richieste ripetute dal modello
            return
        visti.add(chiave)
        flags = list(r.get("flags", []))
        if "rigett" in testo.casefold() and "riconvenzional" in testo.casefold():
            flags.append(
                "La voce sembra unire difesa/eccezione e domanda riconvenzionale: valuta di separarla."
            )
        if da_heuristica:
            flags.append("Voce ricavata dalle conclusioni testuali degli atti: verifica corrispondenza.")
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

    for r in dati_ric.get("richieste", []):
        aggiungi_richiesta(r)
    for r in _estrai_conclusioni_heuristiche(documenti):
        aggiungi_richiesta(r, da_heuristica=True)
    return {"in_fatto": in_fatto, "richieste": richieste}
