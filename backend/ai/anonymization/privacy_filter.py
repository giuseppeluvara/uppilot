"""AnonymizationService verso il servizio Privacy Filter (§95).

Il servizio espone openai/privacy-filter e restituisce testo PSEUDONIMIZZATO
(non anonimizzato) + mappa delle entità mascherate.
"""
from __future__ import annotations

import httpx

from ai.interfaces import AnonymizationResult


class OpenAIPrivacyFilterService:
    def __init__(self, base_url: str, timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def anonymize(self, text: str) -> AnonymizationResult:
        resp = httpx.post(
            f"{self.base_url}/anonymize", json={"text": text}, timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return AnonymizationResult(
            testo_pseudonimizzato=data["testo_pseudonimizzato"],
            mappa_entita=data.get("mappa_entita", {}),
        )
