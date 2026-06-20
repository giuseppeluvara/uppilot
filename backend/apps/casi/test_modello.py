import pytest
from rest_framework.test import APIClient

from apps.casi.models import Documento, Lavoro, SezioneDocumenti


@pytest.fixture
def utente(db, django_user_model):
    return django_user_model.objects.create_user(username="op", password="x")


@pytest.fixture
def client(utente):
    c = APIClient()
    c.force_authenticate(user=utente)
    return c


def test_elimina_documento_caricato(client, utente):
    lavoro = Lavoro.objects.create(utente=utente, titolo="Caso")
    sez = SezioneDocumenti.objects.create(lavoro=lavoro, tipo=SezioneDocumenti.Tipo.ATTORE)
    doc = Documento.objects.create(sezione=sez, file="documenti/x.pdf")

    assert client.delete(f"/api/documenti/{doc.id}/").status_code == 204
    assert not Documento.objects.filter(pk=doc.id).exists()


def test_documento_di_altri_non_eliminabile(client, django_user_model):
    altro = django_user_model.objects.create_user(username="altro", password="x")
    lavoro = Lavoro.objects.create(utente=altro, titolo="Altro")
    sez = SezioneDocumenti.objects.create(lavoro=lavoro, tipo=SezioneDocumenti.Tipo.ATTORE)
    doc = Documento.objects.create(sezione=sez, file="documenti/y.pdf")

    assert client.delete(f"/api/documenti/{doc.id}/").status_code == 404
    assert Documento.objects.filter(pk=doc.id).exists()


def test_imposta_e_cancella_modello_di_redazione(client, utente):
    lavoro = Lavoro.objects.create(utente=utente, titolo="Caso")

    r = client.post(
        f"/api/lavori/{lavoro.id}/modello/",
        {"testo": "PARAGRAFI: Svolgimento; Motivi. STILE: conciso."},
        format="json",
    )
    assert r.status_code == 200
    lavoro.refresh_from_db()
    assert "PARAGRAFI" in lavoro.modello_testo

    # Cancellazione (testo vuoto).
    client.post(f"/api/lavori/{lavoro.id}/modello/", {"testo": ""}, format="json")
    lavoro.refresh_from_db()
    assert lavoro.modello_testo == ""


def test_estrai_modello_da_file_non_salva(client, utente):
    from django.core.files.uploadedfile import SimpleUploadedFile

    lavoro = Lavoro.objects.create(utente=utente, titolo="C")
    f = SimpleUploadedFile("modello.txt", b"STRUTTURA: A; B.", content_type="text/plain")
    r = client.post(f"/api/lavori/{lavoro.id}/estrai-modello/", {"file": f}, format="multipart")
    assert r.status_code == 200
    assert "STRUTTURA" in r.json()["testo"]
    lavoro.refresh_from_db()
    assert lavoro.modello_testo == ""  # l'estrazione NON salva: salva l'operatore


def test_blocco_modello_guida_il_prompt(utente):
    from apps.analisi.services import _blocco_modello

    lavoro = Lavoro.objects.create(utente=utente, titolo="C", modello_testo="Stile X")
    assert "Stile X" in _blocco_modello(lavoro)
    lavoro_vuoto = Lavoro.objects.create(utente=utente, titolo="D")
    assert _blocco_modello(lavoro_vuoto) == ""
