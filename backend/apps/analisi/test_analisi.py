"""Test del blocco analisi LLM (§6/§7) con LLM mockato."""
import json

import pytest
from rest_framework.test import APIClient

from apps.analisi import tasks
from apps.analisi.models import Bozza, Richiesta
from apps.analisi.services import analizza_lavoro
from apps.casi.models import Documento, Lavoro, SezioneDocumenti
from apps.casi.states import StatoLavoro


class FakeLLM:
    """LLMBackend finto: registra il prompt e restituisce un JSON prefissato."""

    def __init__(self, payload):
        self.payload = payload
        self.ultimo_prompt = None
        self.ultimi_opts = None

    def generate(self, prompt, **opts):
        self.ultimo_prompt = prompt
        self.ultimi_opts = opts
        return json.dumps(self.payload)

    def stream(self, prompt, **opts):
        yield self.generate(prompt, **opts)


def _doc_accettato(lavoro, tipo, testo_pseudo):
    sezione = SezioneDocumenti.objects.create(lavoro=lavoro, tipo=tipo)
    return Documento.objects.create(
        sezione=sezione,
        file="x.pdf",
        testo_estratto="ORIGINALE NON DEVE ESSERE USATO",
        testo_pseudonimizzato=testo_pseudo,
        pseudonimizzato=True,
        stato_accettazione=Documento.StatoAccettazione.ACCETTATO_SENZA_VERIFICA,
    )


@pytest.fixture
def lavoro(db, django_user_model):
    u = django_user_model.objects.create_user(username="r", password="x")
    return Lavoro.objects.create(utente=u, titolo="Caso")


def test_analisi_usa_solo_testo_pseudonimizzato(lavoro):
    _doc_accettato(
        lavoro, SezioneDocumenti.Tipo.ATTORE, "[PRIVATE_PERSON_1] chiede 5000 euro."
    )
    llm = FakeLLM({"in_fatto": "Sintesi.", "richieste": []})

    analizza_lavoro(lavoro, llm)

    # Vincolo §119: nel prompt entra SOLO il pseudonimizzato, mai l'originale.
    assert "[PRIVATE_PERSON_1]" in llm.ultimo_prompt
    assert "ORIGINALE" not in llm.ultimo_prompt
    # L'estrazione richieste (ultima chiamata) vincola l'output con uno schema JSON,
    # con thinking disattivato.
    assert isinstance(llm.ultimi_opts.get("format"), dict)
    assert llm.ultimi_opts.get("think") is False


def test_analisi_documento_non_accettato_escluso(lavoro):
    sezione = SezioneDocumenti.objects.create(
        lavoro=lavoro, tipo=SezioneDocumenti.Tipo.ATTORE
    )
    Documento.objects.create(
        sezione=sezione,
        file="x.pdf",
        testo_pseudonimizzato="[PRIVATE_PERSON_9] non accettato",
        pseudonimizzato=True,
        stato_accettazione=Documento.StatoAccettazione.DA_VERIFICARE,
    )
    with pytest.raises(ValueError):
        analizza_lavoro(lavoro, FakeLLM({"in_fatto": "", "richieste": []}))


def test_task_persiste_bozza_richieste_e_transiziona(lavoro, monkeypatch):
    _doc_accettato(
        lavoro, SezioneDocumenti.Tipo.ATTORE, "[PRIVATE_PERSON_1] chiede la risoluzione."
    )
    payload = {
        "in_fatto": "Le parti hanno stipulato un contratto.",
        "richieste": [
            {
                "parte": "attore",
                "testo": "Chiede la risoluzione del contratto.",
                "quesiti_aperti": ["L'onere della prova spetta all'attore? Verifica."],
            }
        ],
    }
    monkeypatch.setattr(tasks, "get_llm_backend", lambda *a, **k: FakeLLM(payload))

    tasks.analizza_lavoro_task(lavoro.id)

    lavoro.refresh_from_db()
    assert lavoro.analisi_stato == Lavoro.StatoAnalisi.COMPLETATA
    assert lavoro.stato == StatoLavoro.BOZZA_GENERATA
    assert Bozza.objects.get(lavoro=lavoro).in_fatto.startswith("Le parti")
    richiesta = Richiesta.objects.get(lavoro=lavoro)
    assert richiesta.parte_richiedente == "attore"
    assert richiesta.quesiti_aperti  # punto discrezionale posto come quesito (§1)


def test_endpoint_analizza_senza_documenti_400(lavoro):
    client = APIClient()
    client.force_authenticate(user=lavoro.utente)
    resp = client.post(f"/api/lavori/{lavoro.id}/analizza/")
    assert resp.status_code == 400


def test_endpoint_analizza_e_bozza(lavoro, monkeypatch):
    _doc_accettato(lavoro, SezioneDocumenti.Tipo.ATTORE, "[PRIVATE_PERSON_1] agisce.")
    monkeypatch.setattr(
        tasks,
        "get_llm_backend",
        lambda *a, **k: FakeLLM({"in_fatto": "Fatto sintetico.", "richieste": []}),
    )
    client = APIClient()
    client.force_authenticate(user=lavoro.utente)

    # Con CELERY_TASK_ALWAYS_EAGER l'analisi gira subito.
    resp = client.post(f"/api/lavori/{lavoro.id}/analizza/")
    assert resp.status_code == 202

    resp_bozza = client.get(f"/api/lavori/{lavoro.id}/bozza/")
    assert resp_bozza.status_code == 200
    assert resp_bozza.data["in_fatto"] == "Fatto sintetico."


def test_analizza_lavoro_altrui_404(lavoro, django_user_model):
    intruso = django_user_model.objects.create_user(username="b", password="x")
    client = APIClient()
    client.force_authenticate(user=intruso)
    resp = client.post(f"/api/lavori/{lavoro.id}/analizza/")
    assert resp.status_code == 404
