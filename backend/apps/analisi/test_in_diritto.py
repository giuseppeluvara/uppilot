"""Test del ragionamento 'in diritto' per richiesta (M2) con LLM mockato."""
import json

import pytest
from rest_framework.test import APIClient

from apps.analisi import tasks
from apps.analisi.models import Richiesta
from apps.analisi.services import approfondisci_richiesta
from apps.casi.models import Documento, Lavoro, SezioneDocumenti


class FakeLLM:
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


def _doc(lavoro, tipo, testo_pseudo):
    sezione = SezioneDocumenti.objects.create(lavoro=lavoro, tipo=tipo)
    return Documento.objects.create(
        sezione=sezione,
        file="x.pdf",
        testo_estratto="ORIGINALE VIETATO",
        testo_pseudonimizzato=testo_pseudo,
        pseudonimizzato=True,
        stato_accettazione=Documento.StatoAccettazione.ACCETTATO_SENZA_VERIFICA,
    )


@pytest.fixture
def scenario(db, django_user_model):
    u = django_user_model.objects.create_user(username="r", password="x")
    lavoro = Lavoro.objects.create(utente=u, titolo="Caso")
    doc = _doc(lavoro, SezioneDocumenti.Tipo.ATTORE, "[PRIVATE_PERSON_1] produce il contratto.")
    richiesta = Richiesta.objects.create(
        lavoro=lavoro,
        parte_richiedente=Richiesta.Parte.ATTORE,
        testo="Chiede l'adempimento del contratto.",
        ordine=0,
    )
    return lavoro, doc, richiesta


def test_approfondisci_usa_pseudonimizzato_e_filtra_allegati(scenario):
    lavoro, doc, richiesta = scenario
    llm = FakeLLM(
        {
            "onere_probatorio": "Spetta all'attore provare il contratto.",
            "allegati": [doc.id, 9999],  # 9999 non esiste -> deve essere scartato
            "non_contestazioni": ["La stipula non è contestata."],
            "quesiti_aperti": ["L'onere spetta all'attore: confermi?"],
        }
    )

    dati = approfondisci_richiesta(richiesta, [doc], llm)

    assert dati["allegati"] == [doc.id]
    assert "[PRIVATE_PERSON_1]" in llm.ultimo_prompt
    assert "ORIGINALE" not in llm.ultimo_prompt
    assert f"Documento {doc.id}" in llm.ultimo_prompt
    assert llm.ultimi_opts.get("format") == "json"
    assert llm.ultimi_opts.get("think") is False


def test_task_popola_richiesta_e_stato(scenario, monkeypatch):
    lavoro, doc, richiesta = scenario
    payload = {
        "onere_probatorio": "Onere a carico dell'attore.",
        "allegati": [doc.id],
        "non_contestazioni": ["Fatto pacifico."],
        "quesiti_aperti": ["La domanda è provata dall'allegato? Verifica."],
    }
    monkeypatch.setattr(tasks, "get_llm_backend", lambda *a, **k: FakeLLM(payload))

    tasks.approfondisci_lavoro_task(lavoro.id)

    lavoro.refresh_from_db()
    richiesta.refresh_from_db()
    assert lavoro.approfondimento_stato == Lavoro.StatoAnalisi.COMPLETATA
    assert richiesta.stato == Richiesta.Stato.APPROFONDITA
    assert richiesta.onere_probatorio.startswith("Onere")
    assert list(richiesta.allegati_collegati.values_list("id", flat=True)) == [doc.id]
    assert richiesta.quesiti_aperti  # discrezionale come quesito (§1)


def test_endpoint_approfondisci(scenario, monkeypatch):
    lavoro, doc, richiesta = scenario
    monkeypatch.setattr(
        tasks,
        "get_llm_backend",
        lambda *a, **k: FakeLLM({"onere_probatorio": "x", "allegati": [], "non_contestazioni": [], "quesiti_aperti": []}),
    )
    client = APIClient()
    client.force_authenticate(user=lavoro.utente)
    resp = client.post(f"/api/lavori/{lavoro.id}/approfondisci/")
    assert resp.status_code == 202


def test_endpoint_approfondisci_senza_richieste_400(db, django_user_model):
    u = django_user_model.objects.create_user(username="r", password="x")
    lavoro = Lavoro.objects.create(utente=u, titolo="Vuoto")
    client = APIClient()
    client.force_authenticate(user=u)
    resp = client.post(f"/api/lavori/{lavoro.id}/approfondisci/")
    assert resp.status_code == 400


def test_approfondisci_lavoro_altrui_404(scenario, django_user_model):
    lavoro, _, _ = scenario
    intruso = django_user_model.objects.create_user(username="b", password="x")
    client = APIClient()
    client.force_authenticate(user=intruso)
    resp = client.post(f"/api/lavori/{lavoro.id}/approfondisci/")
    assert resp.status_code == 404
