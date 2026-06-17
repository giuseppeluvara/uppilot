"""LegalSearchProvider via web search generica (§137).

Non è integrazione di banche dati autoritative (quelle italiane serie sono a
pagamento/login). È una ricerca web generica best-effort: i risultati sono
SPUNTI da valutare, non citazioni date per buone (§6/§1).

La query in ingresso deve già essere pseudonimizzata: questo provider non vede
mai i dati reali delle parti (la pseudonimizzazione è garantita a monte, §134).
"""
from __future__ import annotations

import html
import logging
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from ai.interfaces import SuggerimentoRicerca

logger = logging.getLogger(__name__)


def _url_reale(href: str) -> str:
    """DuckDuckGo incapsula i link in un redirect (//duckduckgo.com/l/?uddg=...):
    estrae l'URL reale, più pulito e corto."""
    if "duckduckgo.com/l/" in href:
        uddg = parse_qs(urlparse(href).query).get("uddg")
        if uddg:
            return unquote(uddg[0])
    return href

# Risultati: <a class="result__a" href="URL">Titolo</a> ... snippet
_RE_RISULTATO = re.compile(
    r'result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<titolo>.*?)</a>.*?'
    r'result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL,
)
_RE_TAG = re.compile(r"<[^>]+>")


def _pulisci(testo: str) -> str:
    return html.unescape(_RE_TAG.sub("", testo)).strip()


class WebLegalSearchProvider:
    def __init__(self, endpoint: str = "https://html.duckduckgo.com/html/", max_risultati: int = 4, timeout: float = 15.0):
        self.endpoint = endpoint
        self.max_risultati = max_risultati
        self.timeout = timeout

    def search(self, query: str) -> list[SuggerimentoRicerca]:
        try:
            resp = httpx.get(
                self.endpoint,
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (UPPilot)"},
                timeout=self.timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:  # rete assente o blocco upstream
            logger.warning("Ricerca web fallita per %r: %s", query, exc)
            return []

        spunti: list[SuggerimentoRicerca] = []
        for m in _RE_RISULTATO.finditer(resp.text):
            titolo = _pulisci(m.group("titolo"))
            snippet = _pulisci(m.group("snippet"))
            if not titolo:
                continue
            spunti.append(
                SuggerimentoRicerca(
                    titolo=titolo, sintesi=snippet, fonte=_url_reale(m.group("url"))[:1000]
                )
            )
            if len(spunti) >= self.max_risultati:
                break
        return spunti
