"""Implementazione OCRBackend basata su GLM-OCR via Ollama (§93).

Nota tecnica: per le richieste vision si usa l'endpoint nativo /api/generate
di Ollama (non quello OpenAI-compatible, che ha limiti sulle immagini).
"""
from __future__ import annotations

import base64

import httpx

from ai.interfaces import OCRResult, OCRMode

# Prompt per le modalità distinte di GLM-OCR (§110).
_PROMPT_MODE = {
    "text": "Text Recognition:",
    "table": "Table Recognition:",
    "figure": "Figure Recognition:",
}


class GlmOcrBackend:
    def __init__(self, base_url: str, model: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def recognize(self, image: bytes, mode: OCRMode = "text") -> OCRResult:
        payload = {
            "model": self.model,
            "prompt": _PROMPT_MODE.get(mode, _PROMPT_MODE["text"]),
            "images": [base64.b64encode(image).decode("ascii")],
            "stream": False,
        }
        resp = httpx.post(
            f"{self.base_url}/api/generate", json=payload, timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return OCRResult(testo=data.get("response", "").strip())
