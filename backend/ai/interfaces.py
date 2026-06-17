"""Interfacce verso i servizi AI (§89).

Il resto della piattaforma deve parlare SOLO con queste astrazioni, mai
direttamente con Ollama o con una libreria specifica. Questo protegge da
abbandono upstream e da lock-in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Literal, Protocol, runtime_checkable

# --- Tipi di risultato ---------------------------------------------------

OCRMode = Literal["text", "table", "figure"]


@dataclass
class OCRResult:
    testo: str
    confidenza: float | None = None
    # Passaggi marcati come incerti (es. manoscritti) da far verificare (§111).
    passaggi_incerti: list[str] = field(default_factory=list)

    @property
    def bassa_confidenza(self) -> bool:
        return bool(self.passaggi_incerti) or (
            self.confidenza is not None and self.confidenza < 0.75
        )


@dataclass
class AnonymizationResult:
    testo_pseudonimizzato: str
    # Mappa placeholder -> valore originale mascherato.
    mappa_entita: dict[str, str] = field(default_factory=dict)


@dataclass
class SuggerimentoRicerca:
    titolo: str
    sintesi: str
    fonte: str | None = None


# --- Interfacce ----------------------------------------------------------

@runtime_checkable
class OCRBackend(Protocol):
    def recognize(self, image: bytes, mode: OCRMode = "text") -> OCRResult: ...


@runtime_checkable
class LLMBackend(Protocol):
    def generate(self, prompt: str, **opts) -> str: ...

    def stream(self, prompt: str, **opts) -> Iterator[str]: ...


@runtime_checkable
class AnonymizationService(Protocol):
    def anonymize(self, text: str) -> AnonymizationResult: ...


@runtime_checkable
class LegalSearchProvider(Protocol):
    # La query esce SEMPRE pseudonimizzata (§134).
    def search(self, query: str) -> list[SuggerimentoRicerca]: ...


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Calcola vettori per il RAG (§83). Resta locale: nessun dato esce."""

    def embed(self, text: str) -> list[float]: ...

    def embed_many(self, texts: list[str]) -> list[list[float]]: ...
