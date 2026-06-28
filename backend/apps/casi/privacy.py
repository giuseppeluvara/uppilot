"""Utility privacy per pseudonimizzazione, coerenza placeholder e leak check."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from collections.abc import Iterable

PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_\d+\]")
BRACKET_TOKEN_RE = re.compile(r"\[[^\]\n]{3,}\]")
_RE_GRUPPO = re.compile(r"\[([A-Z_]+)_\d+\]")

_WORD_RE = re.compile(r"[\wÀ-ÖØ-öø-ÿ']+", re.UNICODE)

_MARKER_AMMESSI = {"[DA DECIDERE]"}

_GRUPPI_PLACEHOLDER_NOTI = {
    "ADDRESS",
    "DATE",
    "EMAIL",
    "GPE",
    "IBAN",
    "LOCATION",
    "LOC",
    "MONEY",
    "ORG",
    "ORGANIZATION",
    "ORGANIZZAZIONE",
    "PERSON",
    "PHONE",
    "PHONE_NUMBER",
    "PRIVATE_ADDRESS",
    "PRIVATE_DATE",
    "PRIVATE_PERSON",
    "TAX_CODE",
    "VAT",
}

_STOP_TOKENS = {
    "alla",
    "alle",
    "allo",
    "art",
    "appalto",
    "atto",
    "atti",
    "audit",
    "avv",
    "causa",
    "civile",
    "cod",
    "codice",
    "complesso",
    "comparsa",
    "conclusionale",
    "condominio",
    "contro",
    "convenuto",
    "convenuta",
    "citazione",
    "del",
    "dell",
    "della",
    "delle",
    "dello",
    "euro",
    "fattura",
    "fascicolo",
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
    "pec",
    "penale",
    "presso",
    "registro",
    "ricorso",
    "sentenza",
    "sig",
    "sigra",
    "societa",
    "srl",
    "spa",
    "tribunale",
    "truffa",
    "ufficio",
    "via",
    "viale",
}

_TOKEN_RESIDUI_GRUPPI = {
    "PERSON",
    "PRIVATE_PERSON",
    "ORG",
    "ORGANIZATION",
    "ORGANIZZAZIONE",
}

_STOP_PHRASES = {
    "corte appello",
    "codice civile",
    "codice procedura",
    "comparsa costituzione",
    "in diritto",
    "in fatto",
    "p q m",
    "registro generale",
    "repubblica italiana",
    "tribunale ordinario",
    "ufficio processo",
}

_SUFFIX_RE = re.compile(
    r"\b(s\.?\s*r\.?\s*l\.?|s\.?\s*p\.?\s*a\.?|s\.?\s*n\.?\s*c\.?|"
    r"s\.?\s*a\.?\s*s\.?|societa|societa'|cooperativa|coop|impresa|ditta)\b",
    re.IGNORECASE,
)


def normalizza_entita(valore: str) -> str:
    """Normalizza un valore reale per riconoscere la stessa entità tra documenti."""
    valore = unicodedata.normalize("NFKD", valore or "")
    valore = "".join(c for c in valore if not unicodedata.combining(c))
    valore = _SUFFIX_RE.sub(" ", valore.casefold())
    valore = re.sub(r"[^\w]+", " ", valore, flags=re.UNICODE)
    return re.sub(r"\s+", " ", valore).strip()


def gruppo_placeholder(placeholder: str) -> str:
    """Restituisce il gruppo di un placeholder, es. PRIVATE_PERSON o DATE."""
    m = _RE_GRUPPO.fullmatch(placeholder or "")
    return m.group(1) if m else ""


def token_significativi(valore: str) -> list[str]:
    """Token abbastanza specifici da essere considerati leak residui."""
    out: list[str] = []
    for token in _WORD_RE.findall(valore or ""):
        norm = normalizza_entita(token)
        if len(norm) < 4 or norm in _STOP_TOKENS or norm.isdecimal():
            continue
        if norm not in out:
            out.append(norm)
    return out


_CAPITALIZED_TOKEN_RE = re.compile(r"\b[A-ZÀ-Ö][\wÀ-ÖØ-öø-ÿ']{3,}\b", re.UNICODE)


def token_extra_significativi(valore: str) -> list[str]:
    """Token da controllare per valori extra come il titolo del lavoro.

    I titoli spesso contengono parole descrittive ("appalto", "penale") che non
    sono dati personali. Qui manteniamo il controllo sui nomi propri/enti e sui
    codici, evitando falsi positivi su categorie del fascicolo.
    """

    valore = valore or ""
    if _SUFFIX_RE.search(valore):
        return token_significativi(valore)
    out: list[str] = []
    for token in _CAPITALIZED_TOKEN_RE.findall(valore):
        norm = normalizza_entita(token)
        if len(norm) < 4 or norm in _STOP_TOKENS or norm.isdecimal():
            continue
        if norm not in out:
            out.append(norm)
    # Una sola parola maiuscola nel titolo è spesso categoria o iniziale frase;
    # due o più token sono invece un buon indizio di parti/enti nel titolo.
    return out if len(out) >= 2 else []


def normalizza_spazi_placeholder(testo: str) -> str:
    """Evita placeholder incollati a parole o punteggiatura dopo la sostituzione."""
    if not testo:
        return testo
    testo = re.sub(r"(?<=[\wÀ-ÖØ-öø-ÿ])(\[[A-Z_]+_\d+\])", r" \1", testo)
    testo = re.sub(r"(?<=[.;:!?])(?=\[[A-Z_]+_\d+\])", " ", testo)
    testo = re.sub(r"(\[[A-Z_]+_\d+\])(?=[\wÀ-ÖØ-öø-ÿ])", r"\1 ", testo)
    testo = re.sub(r"(\[[A-Z_]+_\d+\])(?=\[[A-Z_]+_\d+\])", r"\1 ", testo)
    testo = re.sub(r"(\[[A-Z_]+_\d+\])(?:\s+\1)+", r"\1", testo)
    testo = re.sub(r"\s+([,.;:!?])", r"\1", testo)
    testo = re.sub(r"([(\[])\s+", r"\1", testo)
    testo = re.sub(r"\s+([)\]])", r"\1", testo)
    return re.sub(r"[ \t]{2,}", " ", testo)


def _placeholder_valido(token: str, mappa: dict[str, str] | None = None) -> bool:
    if token in _MARKER_AMMESSI:
        return True
    if not PLACEHOLDER_RE.fullmatch(token or ""):
        return False
    if mappa and token in mappa:
        return True
    gruppo = gruppo_placeholder(token)
    return gruppo in _GRUPPI_PLACEHOLDER_NOTI


def ripara_placeholder_malformed(testo: str, mappa: dict[str, str]) -> str:
    """Corregge placeholder generati con piccole deformazioni dal LLM.

    Esempio reale: ``[ORGANIZZAZIONIONE_1]`` al posto di
    ``[ORGANIZZAZIONE_1]``. Se esiste nella mappa un placeholder con stesso
    indice e gruppo molto simile, lo sostituiamo prima del leak check/export.
    """
    if not testo or not mappa:
        return testo or ""
    validi = [ph for ph in mappa if PLACEHOLDER_RE.fullmatch(ph)]
    if not validi:
        return testo

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        if _placeholder_valido(token, mappa):
            return token
        m = re.fullmatch(r"\[([A-Za-z_]+)_(\d+)\]", token)
        if not m:
            return token
        gruppo, indice = m.groups()
        gruppo = gruppo.upper()
        candidati = [ph for ph in validi if ph.endswith(f"_{indice}]")]
        if not candidati:
            return token
        migliore = max(
            candidati,
            key=lambda ph: SequenceMatcher(None, gruppo, gruppo_placeholder(ph)).ratio(),
        )
        ratio = SequenceMatcher(None, gruppo, gruppo_placeholder(migliore)).ratio()
        return migliore if ratio >= 0.78 else token

    return BRACKET_TOKEN_RE.sub(repl, testo)


def _usa_token_residui(placeholder: str) -> bool:
    return gruppo_placeholder(placeholder) in _TOKEN_RESIDUI_GRUPPI


def _replace_ci(testo: str, needle: str, repl: str) -> str:
    needle = (needle or "").strip()
    if len(needle) < 4:
        return testo
    pattern = re.compile(
        rf"(?<![\w\[]){re.escape(needle)}(?![\w\]])",
        flags=re.IGNORECASE | re.UNICODE,
    )
    return pattern.sub(repl, testo)


def maschera_residui(testo: str, mappa: dict[str, str]) -> str:
    """Maschera valori reali rimasti dopo il filtro privacy.

    Il filtro primario resta il servizio di anonymization; questa è una cintura di
    sicurezza deterministica per esportazioni e output LLM.
    """
    if not testo or not mappa:
        return normalizza_spazi_placeholder(testo or "")

    testo = ripara_placeholder_malformed(testo, mappa)
    for placeholder, reale in sorted(
        mappa.items(), key=lambda kv: len(kv[1] or ""), reverse=True
    ):
        if not placeholder or not PLACEHOLDER_RE.fullmatch(placeholder):
            continue
        testo = _replace_ci(testo, reale or "", placeholder)
        if _usa_token_residui(placeholder):
            for token in token_significativi(reale or ""):
                testo = _replace_ci(testo, token, placeholder)
    return normalizza_spazi_placeholder(testo)


_ROLE_SINGLE_RE = re.compile(
    r"\b(?:avv|ing|geom|dott|dott\.ssa|ctu|ctp|perito|teste|sig|sig\.ra)\.?\s+"
    r"([A-ZÀ-Ö][a-zà-öø-ÿ']{3,})\b"
)
_ORG_CANDIDATE_RE = re.compile(
    r"\b([A-ZÀ-Ö][\wÀ-ÖØ-öø-ÿ'&-]*(?:\s+[A-ZÀ-Ö][\wÀ-ÖØ-öø-ÿ'&-]*){0,5}\s+"
    r"(?:S\.?\s*r\.?\s*l\.?|S\.?\s*p\.?\s*A\.?|S\.?\s*n\.?\s*c\.?|"
    r"S\.?\s*a\.?\s*s\.?|Società|Cooperativa|Impresa|Ditta))\b",
    re.IGNORECASE,
)
_CAPITALIZED_PAIR_RE = re.compile(
    r"\b([A-ZÀ-Ö][a-zà-öø-ÿ']{2,}(?:\s+[A-ZÀ-Ö][a-zà-öø-ÿ']{2,}){1,3})\b"
)


def _gia_nota(candidato: str, valori_noti: list[str]) -> bool:
    norm = normalizza_entita(candidato)
    if not norm:
        return True
    if norm in _STOP_PHRASES:
        return True
    tokens = set(norm.split())
    if tokens and all(t in _STOP_TOKENS for t in tokens):
        return True
    for valore in valori_noti:
        n_valore = normalizza_entita(valore)
        if not n_valore:
            continue
        if norm == n_valore or norm in n_valore or n_valore in norm:
            return True
        val_tokens = set(n_valore.split())
        if tokens and tokens <= val_tokens:
            return True
    return False


def candidati_pii_sconosciuti(testo: str, mappa: dict[str, str]) -> list[dict[str, str]]:
    """Euristica prudente per residui PII non presenti nella mappa del filtro.

    Il privacy filter può produrre mappe incomplete (es. nome spezzato) o lasciare
    un'organizzazione non mascherata. Qui non proviamo a "indovinare" la persona:
    segnaliamo candidati ad alta probabilità per revisione/blocco export.
    """
    corpo = PLACEHOLDER_RE.sub(" ", testo or "")
    valori_noti = [v for v in (mappa or {}).values() if v]
    candidati: list[dict[str, str]] = []
    visti: set[str] = set()

    def aggiungi(valore: str, tipo: str):
        valore = re.sub(r"\s+", " ", (valore or "").strip(" ,.;:()[]"))
        norm = normalizza_entita(valore)
        if len(norm) < 4 or norm in visti or _gia_nota(valore, valori_noti):
            return
        candidati.append({"tipo": tipo, "token": valore})
        visti.add(norm)

    for m in _ORG_CANDIDATE_RE.finditer(corpo):
        aggiungi(m.group(1), "organizzazione")
    for m in _ROLE_SINGLE_RE.finditer(corpo):
        aggiungi(m.group(1), "persona")
    for m in _CAPITALIZED_PAIR_RE.finditer(corpo):
        aggiungi(m.group(1), "persona_o_ente")

    return candidati[:50]


def privacy_report(
    testi: str | Iterable[str],
    mappa: dict[str, str],
    *,
    extra_values: Iterable[str] = (),
) -> dict:
    """Ritorna indicatori sintetici su leak residui e placeholder malformati."""
    if isinstance(testi, str):
        corpo = testi
    else:
        corpo = "\n".join(t for t in testi if t)
    leaks: list[dict[str, str]] = []
    visti: set[tuple[str, str]] = set()
    valori = [(placeholder, reale, False) for placeholder, reale in (mappa or {}).items()]
    valori.extend((f"extra:{i}", v, True) for i, v in enumerate(extra_values) if v)

    for placeholder, reale, extra in valori:
        tokens = token_extra_significativi(reale or "") if extra else token_significativi(reale or "")
        for token in tokens:
            if re.search(rf"(?<![\w\[]){re.escape(token)}(?![\w\]])", corpo, re.IGNORECASE):
                key = (placeholder, token)
                if key not in visti:
                    leaks.append({"placeholder": placeholder, "token": token})
                    visti.add(key)

    malformed = [
        m.group(0)
        for m in BRACKET_TOKEN_RE.finditer(corpo)
        if not _placeholder_valido(m.group(0), dict(mappa or {}))
    ][:20]
    unknown = candidati_pii_sconosciuti(corpo, dict(mappa or {}))
    return {
        "ok": not leaks and not malformed and not unknown,
        "leaks": leaks[:50],
        "unknown_pii": unknown,
        "malformed_placeholders": malformed,
        "warnings": len(leaks) + len(malformed) + len(unknown),
    }
