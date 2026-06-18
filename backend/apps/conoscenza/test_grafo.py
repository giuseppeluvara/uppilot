import json

import pytest
from rest_framework.test import APIClient

from apps.conoscenza import tasks
from apps.conoscenza.models import Arco, Nodo
from apps.conoscenza.services import (
    estrai_grafo_corpus,
    estrai_grafo_lavoro,
    materializza,
    normalizza_chiave,
    upsert_nodo,
)
from apps.corpus.models import DocumentoCorpus

PAYLOAD = {
    "nodi": [
        {"tipo": "riferimento", "etichetta": "Art. 1460 c.c.", "sintesi": "Eccezione di inadempimento."},
        {"tipo": "concetto", "etichetta": "Eccezione di inadempimento", "sintesi": "Rifiuto di adempiere."},
    ],
    "archi": [{"da": "Art. 1460 c.c.", "a": "Eccezione di inadempimento", "tipo": "cita"}],
}


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    def generate(self, prompt, **opts):
        return json.dumps(self.payload)

    def stream(self, prompt, **opts):
        yield self.generate(prompt, **opts)


def test_normalizza_chiave_unifica_varianti():
    assert normalizza_chiave("Eccezione di Inadempimento") == normalizza_chiave(
        "  eccezione  di inadempimento "
    )


@pytest.mark.django_db
def test_materializza_fonde_nodi_e_crea_archi():
    materializza(PAYLOAD)
    assert Nodo.objects.count() == 2
    assert Arco.objects.count() == 1
    # Ri-eseguire non duplica: i nodi sono fusi per chiave, gli archi per (da,a,tipo).
    materializza(PAYLOAD)
    assert Nodo.objects.count() == 2
    assert Arco.objects.count() == 1


@pytest.mark.django_db
def test_estrai_grafo_corpus_collega_al_documento():
    doc = DocumentoCorpus.objects.create(
        titolo="Norme", testo="Testo di prova.", stato=DocumentoCorpus.Stato.COMPLETATO
    )
    estrai_grafo_corpus(doc, FakeLLM(PAYLOAD))
    assert Nodo.objects.filter(documento=doc).count() == 2


@pytest.mark.django_db
def test_endpoint_costruisci_grafo_e_delete(django_user_model, monkeypatch):
    django_user_model.objects.create_user(username="g", password="x")
    DocumentoCorpus.objects.create(
        titolo="Norme", testo="Testo.", stato=DocumentoCorpus.Stato.COMPLETATO
    )
    monkeypatch.setattr(tasks, "get_llm_backend", lambda *a, **k: FakeLLM(PAYLOAD))

    client = APIClient()
    client.force_authenticate(user=django_user_model.objects.get(username="g"))

    # Costruzione (Celery eager → sincrona).
    assert client.post("/api/grafo/costruisci/").status_code == 202

    grafo = client.get("/api/grafo/").json()
    assert len(grafo["nodi"]) == 2 and len(grafo["archi"]) == 1
    assert client.get("/api/grafo/stato/").json()["n_nodi"] == 2

    nodo_id = grafo["nodi"][0]["id"]
    assert client.delete(f"/api/grafo/nodo/{nodo_id}/").status_code == 204
    assert Nodo.objects.count() == 1


@pytest.mark.django_db
def test_estrai_grafo_lavoro_crea_caso_anonimo(django_user_model):
    from apps.analisi.models import Bozza, Richiesta
    from apps.casi.models import Lavoro

    u = django_user_model.objects.create_user(username="a", password="x")
    lav = Lavoro.objects.create(utente=u, titolo="Rossi c. Bianchi")  # titolo con nomi
    Bozza.objects.create(lavoro=lav, in_fatto="Tra [PRIVATE_PERSON_1] e [PRIVATE_PERSON_2]...")
    Richiesta.objects.create(lavoro=lav, parte_richiedente="attore", testo="X", ordine=0)

    estrai_grafo_lavoro(
        lav, FakeLLM({"riferimenti": ["Art. 1460 c.c.", "Eccezione di inadempimento"]})
    )
    caso = Nodo.objects.get(tipo="caso", lavoro=lav)
    assert caso.etichetta == f"Fascicolo #{lav.id}"  # ANONIMO: niente nomi delle parti
    assert Arco.objects.filter(da=caso, tipo="applica").count() == 2


@pytest.mark.django_db
def test_grafo_scoping_casi_per_utente(django_user_model):
    from apps.casi.models import Lavoro

    ua = django_user_model.objects.create_user(username="a", password="x")
    ub = django_user_model.objects.create_user(username="b", password="x")
    lav = Lavoro.objects.create(utente=ua, titolo="X")
    upsert_nodo("Fascicolo #1", tipo="caso", lavoro=lav, chiave=f"caso:{lav.id}")
    upsert_nodo("Concetto condiviso", tipo="concetto")  # corpus globale

    client = APIClient()
    client.force_authenticate(user=ub)
    nodi = client.get("/api/grafo/").json()["nodi"]
    etichette = {n["etichetta"] for n in nodi}
    assert "Concetto condiviso" in etichette  # corpus condiviso → visibile a tutti
    assert all(n["tipo"] != "caso" for n in nodi)  # il caso di A NON è visibile a B
