"""LLMBackend commerciale (OPT-IN, §94).

Attivabile solo come opt-in esplicito, sempre su testo pseudonimizzato e con
warning GDPR inequivocabile (§125). Provider di riferimento: Anthropic (Claude),
usato tramite l'SDK ufficiale `anthropic`.
"""
from __future__ import annotations

from typing import Iterator

# Default: il modello Claude più capace.
_DEFAULT_MODEL = "claude-opus-4-8"
# Le opzioni di Ollama (format/think/temperature…) non valgono per Anthropic e
# alcune (es. temperature) darebbero 400 su Opus 4.8: vanno ignorate.
_MAX_TOKENS = 8000


class CommercialLLMBackend:
    def __init__(self, provider: str, api_key: str, model: str = "", client=None):
        self.provider = provider
        self.model = model or _DEFAULT_MODEL
        if provider != "anthropic":
            raise ValueError(
                f"Provider commerciale non supportato: {provider!r}. "
                "Attualmente è implementato solo 'anthropic'."
            )
        if client is not None:
            self._client = client
        else:
            import anthropic

            self._client = anthropic.Anthropic(api_key=api_key)

    def generate(self, prompt: str, **opts) -> str:
        max_tokens = int(opts.get("max_tokens", _MAX_TOKENS))
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")

    def stream(self, prompt: str, **opts) -> Iterator[str]:
        max_tokens = int(opts.get("max_tokens", _MAX_TOKENS))
        with self._client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for testo in stream.text_stream:
                yield testo
