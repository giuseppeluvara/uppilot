"""Test delle astrazioni AI con client HTTP mockati (nessun servizio reale)."""
import httpx

from ai.anonymization.privacy_filter import OpenAIPrivacyFilterService
from ai.interfaces import (
    AnonymizationService,
    LLMBackend,
    OCRBackend,
    OCRResult,
)
from ai.ocr.glm_ocr import GlmOcrBackend


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_glm_ocr_recognize(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        assert url.endswith("/api/generate")
        assert json["images"]  # immagine codificata base64 presente
        return _FakeResponse({"response": "  testo estratto  "})

    monkeypatch.setattr(httpx, "post", fake_post)
    backend = GlmOcrBackend(base_url="http://ollama:11434", model="glm-ocr:latest")
    result = backend.recognize(b"\x89PNG fake-bytes")
    assert isinstance(result, OCRResult)
    assert result.testo == "testo estratto"
    assert isinstance(backend, OCRBackend)  # rispetta il Protocol


def test_privacy_filter_anonymize(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        assert url.endswith("/anonymize")
        return _FakeResponse(
            {
                "testo_pseudonimizzato": "[PERSON_1] vive a [LOCATION_1]",
                "mappa_entita": {"[PERSON_1]": "Mario Rossi", "[LOCATION_1]": "Roma"},
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    service = OpenAIPrivacyFilterService(base_url="http://privacy-filter:8000")
    result = service.anonymize("Mario Rossi vive a Roma")
    assert result.testo_pseudonimizzato.startswith("[PERSON_1]")
    assert result.mappa_entita["[PERSON_1]"] == "Mario Rossi"
    assert isinstance(service, AnonymizationService)


def test_ollama_backend_rispetta_protocol():
    from ai.llm.ollama import OllamaLLMBackend

    backend = OllamaLLMBackend(base_url="http://ollama:11434", model="qwen2.5")
    assert isinstance(backend, LLMBackend)


def test_ollama_generate_payload(monkeypatch):
    """format/think vanno al primo livello; il resto dentro options."""
    from ai.llm.ollama import OllamaLLMBackend

    catturato = {}

    def fake_post(url, json=None, timeout=None):
        catturato.update(json)
        return _FakeResponse({"response": "{}"})

    monkeypatch.setattr(httpx, "post", fake_post)
    backend = OllamaLLMBackend(base_url="http://ollama:11434", model="qwen3:8b")
    backend.generate("ciao", format="json", think=False, temperature=0.2)

    assert catturato["format"] == "json"
    assert catturato["think"] is False
    assert catturato["options"] == {"temperature": 0.2}
    assert "format" not in catturato["options"]
