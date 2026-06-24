"""Test della ricerca giuridica 'spunti' (§6) con LLM/provider/anonimizzazione mockati."""
import json

import httpx
import pytest
from rest_framework.test import APIClient

from ai.interfaces import AnonymizationResult, SuggerimentoRicerca
from ai.search.web import WebLegalSearchProvider
from apps.analisi import tasks
from apps.analisi.models import Bozza, Richiesta, SpuntoRicerca
from apps.analisi.ricerca import pseudonimizza_query
from apps.casi.models import Lavoro


class FakeLLM:
    """Risponde con JSON diverso a seconda della fase (proposta query vs sintesi)."""

    def generate(self, prompt, **opts):
        if '"ricerche"' in prompt:
            return json.dumps(
                {"ricerche": [{"argomento": "Risoluzione contratto", "query": "risoluzione contratto inadempimento"}]}
            )
        return json.dumps(
            {"sintesi": "La ricerca web suggerisce orientamenti in materia.", "suggerimento": "Valuta di integrare."}
        )

    def stream(self, prompt, **opts):
        yield self.generate(prompt, **opts)


class FakeProvider:
    def __init__(self):
        self.query_ricevuta = None

    def search(self, query):
        self.query_ricevuta = query
        return [SuggerimentoRicerca(titolo="Cass. civ.", sintesi="massima", fonte="https://x")]


class FakeAnon:
    """Maschera qualunque query (simula la pseudonimizzazione in uscita)."""

    def anonymize(self, text):
        return AnonymizationResult("query pseudonimizzata", {})


class FakeAnonVuoto:
    def anonymize(self, text):
        return AnonymizationResult("", {})


@pytest.fixture
def lavoro(db, django_user_model):
    u = django_user_model.objects.create_user(username="r", password="x")
    lavoro = Lavoro.objects.create(utente=u, titolo="Caso")
    Bozza.objects.create(lavoro=lavoro, in_fatto="[PRIVATE_PERSON_1] chiede la risoluzione.")
    Richiesta.objects.create(
        lavoro=lavoro, parte_richiedente=Richiesta.Parte.ATTORE, testo="Risoluzione.", ordine=0
    )
    return lavoro


def test_web_provider_parsa_risultati(monkeypatch):
    html_ddg = (
        '<a class="result__a" href="https://giuri.it/1">Cassazione 123</a>'
        '<a class="result__snippet">Massima sul contratto</a>'
    )

    class R:
        text = html_ddg

        def raise_for_status(self):
            return None

    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    risultati = WebLegalSearchProvider().search("contratto")
    assert risultati[0].titolo == "Cassazione 123"
    assert risultati[0].fonte == "https://giuri.it/1"


def test_web_provider_errore_rete_ritorna_vuoto(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", boom)
    assert WebLegalSearchProvider().search("x") == []


def test_task_web_query_esce_pseudonimizzata(lavoro, monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(tasks, "get_llm_backend", lambda *a, **k: FakeLLM())
    monkeypatch.setattr(tasks, "get_legal_search_provider", lambda: provider)
    monkeypatch.setattr(tasks, "get_anonymization_service", lambda: FakeAnon())

    tasks.ricerca_spunti_task(lavoro.id)

    lavoro.refresh_from_db()
    assert lavoro.ricerca_stato == Lavoro.StatoAnalisi.COMPLETATA
    # §134: alla ricerca esterna è arrivata la query pseudonimizzata, non i dati reali.
    assert provider.query_ricevuta == "query pseudonimizzata"
    spunto = SpuntoRicerca.objects.get(lavoro=lavoro)
    assert spunto.origine == SpuntoRicerca.Origine.WEB
    assert spunto.query_pseudonimizzata == "query pseudonimizzata"
    assert "suggerisce" in spunto.sintesi


def test_query_esterna_fallisce_se_pseudonimizzazione_vuota():
    with pytest.raises(ValueError):
        pseudonimizza_query("Mario Rossi inadempimento", FakeAnonVuoto())


def test_task_manuale_crea_spunto(lavoro, monkeypatch):
    monkeypatch.setattr(tasks, "get_llm_backend", lambda *a, **k: FakeLLM())
    tasks.ricerca_manuale_task(lavoro.id, "Onere prova", "testo incollato dei risultati")
    spunto = SpuntoRicerca.objects.get(lavoro=lavoro, origine=SpuntoRicerca.Origine.MANUALE)
    assert spunto.argomento == "Onere prova"
    assert spunto.suggerimento
    assert spunto.sintesi.startswith("Dai risultati incollati emerge")


def test_endpoint_ricerca_e_manuale(lavoro, monkeypatch):
    monkeypatch.setattr(tasks, "get_llm_backend", lambda *a, **k: FakeLLM())
    monkeypatch.setattr(tasks, "get_legal_search_provider", lambda: FakeProvider())
    monkeypatch.setattr(tasks, "get_anonymization_service", lambda: FakeAnon())
    client = APIClient()
    client.force_authenticate(user=lavoro.utente)

    assert client.post(f"/api/lavori/{lavoro.id}/ricerca/").status_code == 202
    assert client.post(f"/api/lavori/{lavoro.id}/ricerca/manuale/", {}, format="json").status_code == 400
    ok = client.post(
        f"/api/lavori/{lavoro.id}/ricerca/manuale/", {"materiale": "risultati"}, format="json"
    )
    assert ok.status_code == 202
    assert client.get(f"/api/lavori/{lavoro.id}/spunti/").status_code == 200


def test_ricerca_lavoro_altrui_404(lavoro, django_user_model):
    intruso = django_user_model.objects.create_user(username="b", password="x")
    client = APIClient()
    client.force_authenticate(user=intruso)
    assert client.post(f"/api/lavori/{lavoro.id}/ricerca/").status_code == 404
