"""Test dell'LLM commerciale opt-in (§5/§94) con client Anthropic mockato."""
import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from ai.factory import commerciale_disponibile, get_llm_backend
from ai.interfaces import LLMBackend
from ai.llm.commercial import CommercialLLMBackend
from apps.casi.models import Documento, Lavoro, SezioneDocumenti


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]


class _FakeMessages:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return _Resp('{"ok": true}')


class _FakeAnthropic:
    def __init__(self):
        self.messages = _FakeMessages()


def test_commercial_generate_ignora_opts_ollama():
    fake = _FakeAnthropic()
    backend = CommercialLLMBackend("anthropic", "k", "claude-opus-4-8", client=fake)

    out = backend.generate("ciao", format="json", think=False, temperature=0.2)

    assert out == '{"ok": true}'
    kw = fake.messages.kwargs
    assert kw["model"] == "claude-opus-4-8"
    assert kw["messages"] == [{"role": "user", "content": "ciao"}]
    # temperature/format/think NON vanno inviati ad Anthropic (Opus 4.8 darebbe 400).
    assert "temperature" not in kw
    assert "format" not in kw
    assert "think" not in kw
    assert isinstance(backend, LLMBackend)


def test_provider_non_supportato():
    with pytest.raises(ValueError):
        CommercialLLMBackend("openai", "k", "gpt", client=_FakeAnthropic())


@override_settings(COMMERCIAL_LLM_API_KEY="")
def test_factory_commerciale_non_configurato():
    assert commerciale_disponibile() is False
    with pytest.raises(RuntimeError):
        get_llm_backend(commerciale=True)


@override_settings(
    COMMERCIAL_LLM_API_KEY="chiave",
    COMMERCIAL_LLM_PROVIDER="anthropic",
    COMMERCIAL_LLM_MODEL="claude-opus-4-8",
)
def test_factory_commerciale_ok():
    assert commerciale_disponibile() is True
    backend = get_llm_backend(commerciale=True)
    assert isinstance(backend, CommercialLLMBackend)
    assert backend.model == "claude-opus-4-8"


@override_settings(COMMERCIAL_LLM_API_KEY="")
@pytest.mark.django_db
def test_endpoint_commerciale_non_configurato_400(django_user_model):
    u = django_user_model.objects.create_user(username="r", password="x")
    lavoro = Lavoro.objects.create(utente=u, titolo="Caso")
    sezione = SezioneDocumenti.objects.create(
        lavoro=lavoro, tipo=SezioneDocumenti.Tipo.ATTORE
    )
    Documento.objects.create(
        sezione=sezione,
        file="x.pdf",
        testo_pseudonimizzato="[PRIVATE_PERSON_1] agisce.",
        pseudonimizzato=True,
        stato_accettazione=Documento.StatoAccettazione.ACCETTATO_SENZA_VERIFICA,
    )
    client = APIClient()
    client.force_authenticate(user=u)

    resp = client.post(
        f"/api/lavori/{lavoro.id}/analizza/", {"commerciale": True}, format="json"
    )
    assert resp.status_code == 400
    assert "commerciale" in resp.data["detail"].lower()
