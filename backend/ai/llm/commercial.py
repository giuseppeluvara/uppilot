"""LLMBackend commerciale (OPT-IN, §94).

Attivabile solo come opt-in esplicito, sempre su testo pseudonimizzato e con
warning GDPR inequivocabile (§125). Provider supportati: Anthropic (Claude) e
Google Gemini, tramite gli SDK ufficiali.
"""
from __future__ import annotations

from typing import Iterator

_DEFAULT_MODEL = {
    "anthropic": "claude-opus-4-8",
    "gemini": "gemini-2.5-flash",
}
_MAX_TOKENS = 8000
_PROVIDER_SUPPORTATI = ("anthropic", "gemini")


class CommercialLLMBackend:
    def __init__(self, provider: str, api_key: str, model: str = "", client=None):
        self.provider = provider
        if provider not in _PROVIDER_SUPPORTATI:
            raise ValueError(
                f"Provider commerciale non supportato: {provider!r}. "
                f"Disponibili: {', '.join(_PROVIDER_SUPPORTATI)}."
            )
        self.model = model or _DEFAULT_MODEL[provider]
        if client is not None:
            self._client = client
        elif provider == "anthropic":
            import anthropic

            self._client = anthropic.Anthropic(api_key=api_key)
        else:  # gemini
            from google import genai

            self._client = genai.Client(api_key=api_key)

    # --- API pubblica -------------------------------------------------------

    def generate(self, prompt: str, **opts) -> str:
        if self.provider == "anthropic":
            return self._anthropic_generate(prompt, **opts)
        return self._gemini_generate(prompt, **opts)

    def stream(self, prompt: str, **opts) -> Iterator[str]:
        if self.provider == "anthropic":
            yield from self._anthropic_stream(prompt, **opts)
        else:
            yield from self._gemini_stream(prompt, **opts)

    # --- Anthropic ----------------------------------------------------------
    # Le opzioni di Ollama (format/think/temperature…) non valgono per Anthropic
    # e alcune (es. temperature) darebbero 400 su Opus 4.8: vanno ignorate.

    def _anthropic_generate(self, prompt: str, **opts) -> str:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=int(opts.get("max_tokens", _MAX_TOKENS)),
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")

    def _anthropic_stream(self, prompt: str, **opts) -> Iterator[str]:
        with self._client.messages.stream(
            model=self.model,
            max_tokens=int(opts.get("max_tokens", _MAX_TOKENS)),
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for testo in stream.text_stream:
                yield testo

    # --- Gemini -------------------------------------------------------------
    # `format` (json o schema) → response_mime_type JSON, per output strutturato.

    def _gemini_config(self, opts: dict):
        from google.genai import types

        cfg: dict = {
            "max_output_tokens": int(opts.get("max_tokens", _MAX_TOKENS)),
            # I modelli 2.5 hanno il "thinking" attivo di default: consuma token di
            # output e per l'estrazione strutturata non serve. Lo disattiviamo.
            "thinking_config": types.ThinkingConfig(thinking_budget=0),
        }
        if opts.get("format"):
            cfg["response_mime_type"] = "application/json"
        return types.GenerateContentConfig(**cfg)

    def _gemini_generate(self, prompt: str, **opts) -> str:
        resp = self._client.models.generate_content(
            model=self.model, contents=prompt, config=self._gemini_config(opts)
        )
        return resp.text or ""

    def _gemini_stream(self, prompt: str, **opts) -> Iterator[str]:
        for chunk in self._client.models.generate_content_stream(
            model=self.model, contents=prompt, config=self._gemini_config(opts)
        ):
            if getattr(chunk, "text", None):
                yield chunk.text
