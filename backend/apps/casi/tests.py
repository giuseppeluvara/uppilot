import pytest
from rest_framework.test import APIClient

from apps.casi.models import Documento, Lavoro, SezioneDocumenti
from apps.casi.states import StatoLavoro, TransizioneNonValida


@pytest.fixture
def utente(django_user_model):
    return django_user_model.objects.create_user(username="redattore", password="x")


@pytest.mark.django_db
def test_transizione_valida(utente):
    lavoro = Lavoro.objects.create(utente=utente, titolo="Caso 1")
    lavoro.transiziona(StatoLavoro.ANALIZZATO)
    assert lavoro.stato == StatoLavoro.ANALIZZATO


@pytest.mark.django_db
def test_transizione_non_valida(utente):
    lavoro = Lavoro.objects.create(utente=utente, titolo="Caso 1")
    with pytest.raises(TransizioneNonValida):
        lavoro.transiziona(StatoLavoro.COMPLETATO)


@pytest.mark.django_db
def test_documento_utilizzabile_solo_se_accettato(utente):
    lavoro = Lavoro.objects.create(utente=utente, titolo="Caso 1")
    sezione = SezioneDocumenti.objects.create(
        lavoro=lavoro, tipo=SezioneDocumenti.Tipo.ATTORE
    )
    doc = Documento.objects.create(sezione=sezione, file="x.pdf", pseudonimizzato=True)
    assert doc.utilizzabile is False  # default: da_verificare
    doc.stato_accettazione = Documento.StatoAccettazione.ACCETTATO_SENZA_VERIFICA
    assert doc.utilizzabile is True


@pytest.mark.django_db
def test_creazione_lavoro_genera_tre_sezioni(utente):
    client = APIClient()
    client.force_authenticate(user=utente)
    resp = client.post("/api/lavori/", {"titolo": "Nuovo caso"}, format="json")
    assert resp.status_code == 201
    lavoro = Lavoro.objects.get(id=resp.data["id"])
    assert lavoro.sezioni.count() == 3
    assert set(lavoro.sezioni.values_list("tipo", flat=True)) == set(
        SezioneDocumenti.Tipo.values
    )
