"""Factory dei backend AI (§91).

Punto unico in cui si istanziano le implementazioni concrete a partire dalle
impostazioni Django. Il resto del codice chiede qui le interfacce e non conosce
mai i dettagli (Ollama, HTTP, provider commerciali).
"""
from __future__ import annotations

from django.conf import settings

from ai.anonymization.privacy_filter import OpenAIPrivacyFilterService
from ai.interfaces import (
    AnonymizationService,
    LegalSearchProvider,
    LLMBackend,
    OCRBackend,
)
from ai.llm.ollama import OllamaLLMBackend
from ai.ocr.glm_ocr import GlmOcrBackend
from ai.search.stub import StubLegalSearchProvider


def get_ocr_backend() -> OCRBackend:
    return GlmOcrBackend(base_url=settings.OLLAMA_BASE_URL, model=settings.OCR_MODEL)


def commerciale_disponibile() -> bool:
    """True se l'LLM commerciale è configurato (chiave presente, §5)."""
    return bool(settings.COMMERCIAL_LLM_API_KEY)


def get_llm_backend(commerciale: bool = False) -> LLMBackend:
    """Restituisce l'LLM da usare.

    Default: locale (Ollama). L'LLM commerciale in cloud è OPT-IN (§5):
    si attiva solo se `commerciale=True` (richiesta esplicita per-azione) e
    richiede una chiave configurata.
    """
    if commerciale:
        if not commerciale_disponibile():
            raise RuntimeError(
                "LLM commerciale non configurato: manca COMMERCIAL_LLM_API_KEY."
            )
        from ai.llm.commercial import CommercialLLMBackend

        return CommercialLLMBackend(
            provider=settings.COMMERCIAL_LLM_PROVIDER,
            api_key=settings.COMMERCIAL_LLM_API_KEY,
            model=settings.COMMERCIAL_LLM_MODEL,
        )
    return OllamaLLMBackend(
        base_url=settings.OLLAMA_BASE_URL, model=settings.LLM_MODEL
    )


def get_anonymization_service() -> AnonymizationService:
    return OpenAIPrivacyFilterService(base_url=settings.PRIVACY_FILTER_URL)


def get_embedding_backend():
    """EmbeddingBackend locale per il RAG (§83)."""
    from ai.embeddings.ollama import OllamaEmbeddingBackend

    return OllamaEmbeddingBackend(
        base_url=settings.OLLAMA_BASE_URL, model=settings.EMBEDDING_MODEL
    )


def get_legal_search_provider() -> LegalSearchProvider:
    # "web" = ricerca web generica (§137); "stub" = nessuna ricerca (default
    # prudente, local-first). La query esce sempre pseudonimizzata (§134).
    if getattr(settings, "LEGAL_SEARCH_BACKEND", "stub") == "web":
        from ai.search.web import WebLegalSearchProvider

        return WebLegalSearchProvider()
    return StubLegalSearchProvider()
