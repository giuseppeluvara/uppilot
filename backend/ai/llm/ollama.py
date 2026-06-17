"""LLMBackend locale via Ollama (default in produzione su fascicoli reali, §125)."""
from __future__ import annotations

import json
from typing import Iterator

import httpx


class OllamaLLMBackend:
    def __init__(self, base_url: str, model: str, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    # Parametri Ollama che vivono al primo livello del payload (non in "options").
    _TOP_LEVEL = ("format", "think", "system", "keep_alive")

    def _payload(self, prompt: str, stream: bool, opts: dict) -> dict:
        payload = {"model": self.model, "prompt": prompt, "stream": stream}
        for chiave in self._TOP_LEVEL:
            if chiave in opts:
                payload[chiave] = opts.pop(chiave)
        payload["options"] = opts
        return payload

    def generate(self, prompt: str, **opts) -> str:
        payload = self._payload(prompt, stream=False, opts=opts)
        resp = httpx.post(
            f"{self.base_url}/api/generate", json=payload, timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json().get("response", "")

    def stream(self, prompt: str, **opts) -> Iterator[str]:
        payload = self._payload(prompt, stream=True, opts=opts)
        with httpx.stream(
            "POST", f"{self.base_url}/api/generate", json=payload, timeout=self.timeout
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("response"):
                    yield chunk["response"]
