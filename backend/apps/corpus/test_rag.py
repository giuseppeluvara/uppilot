"""Test del RAG su pgvector (§83) con EmbeddingBackend finto deterministico."""
import pytest
from rest_framework.test import APIClient

from apps.corpus import tasks, views
from apps.corpus.models import DocumentoCorpus, FrammentoCorpus
from apps.corpus.services import cerca, chunk, indicizza

DIM = 768


def _vec(idx: int) -> list[float]:
    v = [0.0] * DIM
    v[idx % DIM] = 1.0
    return v


class FakeEmbedding:
    """Vettore ortonormale per parola chiave: distanza coseno prevedibile."""

    def _idx(self, text: str) -> int:
        t = text.lower()
        if "prescrizione" in t:
            return 1
        if "contratto" in t:
            return 0
        return 2

    def embed(self, text: str) -> list[float]:
        return _vec(self._idx(text))

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def test_chunk_spezza_testo_lungo():
    testo = "a" * 2000
    pezzi = chunk(testo)
    assert len(pezzi) >= 2
    assert all(len(p) <= 800 for p in pezzi)


@pytest.mark.django_db
def test_indicizza_crea_frammenti_con_embedding():
    doc = DocumentoCorpus.objects.create(titolo="Contratti", testo="Sul contratto.")
    n = indicizza(doc, FakeEmbedding())
    assert n == doc.frammenti.count() >= 1
    assert FrammentoCorpus.objects.filter(documento=doc, embedding__isnull=False).exists()


@pytest.mark.django_db
def test_cerca_ritorna_il_frammento_piu_vicino():
    emb = FakeEmbedding()
    d1 = DocumentoCorpus.objects.create(titolo="Contratto", testo="Disciplina del contratto.")
    d2 = DocumentoCorpus.objects.create(titolo="Prescrizione", testo="Termini di prescrizione.")
    indicizza(d1, emb)
    indicizza(d2, emb)

    risultati = cerca("questione sul contratto", emb, k=1)

    assert len(risultati) == 1
    assert "contratto" in risultati[0].testo.lower()


@pytest.mark.django_db
def test_endpoint_ingest_indicizza(django_user_model, monkeypatch):
    monkeypatch.setattr(tasks, "get_embedding_backend", lambda: FakeEmbedding())
    utente = django_user_model.objects.create_user(username="r", password="x")
    client = APIClient()
    client.force_authenticate(user=utente)

    resp = client.post(
        "/api/corpus/ingest/",
        {"titolo": "Cass. 123", "fonte": "x", "testo": "Massima sul contratto."},
        format="json",
    )
    assert resp.status_code == 202
    doc = DocumentoCorpus.objects.get(id=resp.data["id"])
    # Con CELERY_TASK_ALWAYS_EAGER l'indicizzazione è già avvenuta.
    assert doc.stato == DocumentoCorpus.Stato.COMPLETATO
    assert doc.frammenti.exists()


@pytest.mark.django_db
def test_endpoint_cerca(django_user_model, monkeypatch):
    monkeypatch.setattr(views, "get_embedding_backend", lambda: FakeEmbedding())
    doc = DocumentoCorpus.objects.create(titolo="Contratto", testo="Sul contratto.")
    indicizza(doc, FakeEmbedding())
    utente = django_user_model.objects.create_user(username="r", password="x")
    client = APIClient()
    client.force_authenticate(user=utente)

    resp = client.get("/api/corpus/cerca/", {"q": "contratto"})
    assert resp.status_code == 200
    assert resp.data
    assert "contratto" in resp.data[0]["testo"].lower()


@pytest.mark.django_db
def test_cerca_richiede_auth():
    assert APIClient().get("/api/corpus/cerca/", {"q": "x"}).status_code == 403
