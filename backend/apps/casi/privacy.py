"""Utility privacy per pseudonimizzazione, coerenza placeholder e leak check."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_\d+\]")

_WORD_RE = re.compile(r"[\wÀ-ÖØ-öø-ÿ']+", re.UNICODE)

_STOP_TOKENS = {
    "alla",
    "alle",
    "allo",
    "art",
    "atto",
    "atti",
    "avv",
    "civile",
    "cod",
    "codice",
    "contro",
    "del",
    "dell",
    "della",
    "delle",
    "dello",
    "euro",
    "fattura",
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
    "presso",
    "sentenza",
    "sig",
    "sigra",
    "societa",
    "srl",
    "spa",
    "tribunale",
    "via",
    "viale",
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


def normalizza_spazi_placeholder(testo: str) -> str:
    """Evita placeholder incollati a parole o punteggiatura dopo la sostituzione."""
    if not testo:
        return testo
    testo = re.sub(r"(?<=[\wÀ-ÖØ-öø-ÿ])(\[[A-Z_]+_\d+\])", r" \1", testo)
    testo = re.sub(r"(\[[A-Z_]+_\d+\])(?=[\wÀ-ÖØ-öø-ÿ])", r"\1 ", testo)
    testo = re.sub(r"\s+([,.;:!?])", r"\1", testo)
    testo = re.sub(r"([(\[])\s+", r"\1", testo)
    testo = re.sub(r"\s+([)\]])", r"\1", testo)
    return re.sub(r"[ \t]{2,}", " ", testo)


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

    for placeholder, reale in sorted(
        mappa.items(), key=lambda kv: len(kv[1] or ""), reverse=True
    ):
        if not placeholder or not PLACEHOLDER_RE.fullmatch(placeholder):
            continue
        testo = _replace_ci(testo, reale or "", placeholder)
        for token in token_significativi(reale or ""):
            testo = _replace_ci(testo, token, placeholder)
    return normalizza_spazi_placeholder(testo)


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
    valori = list((mappa or {}).items())
    valori.extend((f"extra:{i}", v) for i, v in enumerate(extra_values) if v)

    for placeholder, reale in valori:
        for token in token_significativi(reale or ""):
            if re.search(rf"(?<![\w\[]){re.escape(token)}(?![\w\]])", corpo, re.IGNORECASE):
                key = (placeholder, token)
                if key not in visti:
                    leaks.append({"placeholder": placeholder, "token": token})
                    visti.add(key)

    malformed = [
        m.group(0)
        for m in re.finditer(r"\[[^\]\s]{3,}\]", corpo)
        if not PLACEHOLDER_RE.fullmatch(m.group(0))
    ][:20]
    return {
        "ok": not leaks and not malformed,
        "leaks": leaks[:50],
        "malformed_placeholders": malformed,
        "warnings": len(leaks) + len(malformed),
    }
