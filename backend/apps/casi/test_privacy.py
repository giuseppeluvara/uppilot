"""Test del blocco privacy: pseudonimizzazione e flusso di accettazione (§119/§122)."""
import pytest
from rest_framework.test import APIClient

from ai.interfaces import AnonymizationResult
from apps.casi.models import Documento, Lavoro, SezioneDocumenti
from apps.casi import tasks


@pytest.fixture
def documento(db, django_user_model):
    utente = django_user_model.objects.create_user(username="r", password="x")
    lavoro = Lavoro.objects.create(utente=utente, titolo="Caso")
    sezione = SezioneDocumenti.objects.create(
        lavoro=lavoro, tipo=SezioneDocumenti.Tipo.ATTORE
    )
    doc = Documento.objects.create(
        sezione=sezione,
        file="x.pdf",
        testo_estratto="Mario Rossi residente a Roma.",
        stato_estrazione=Documento.StatoEstrazione.COMPLETATO,
    )
    return doc


def test_pseudonimizzazione_popola_campi(documento, monkeypatch):
    monkeypatch.setattr(
        tasks,
        "get_anonymization_service",
        lambda: type(
            "S",
            (),
            {
                "anonymize": lambda self, t: AnonymizationResult(
                    "[PERSON_1] residente a [LOCATION_1].",
                    {"[PERSON_1]": "Mario Rossi", "[LOCATION_1]": "Roma"},
                )
            },
        )(),
    )

    tasks.pseudonimizza_documento(documento.id)

    documento.refresh_from_db()
    assert documento.pseudonimizzato is True
    assert "[PERSON_1]" in documento.testo_pseudonimizzato
    assert documento.mappa_entita["[PERSON_1]"] == "Mario Rossi"


def test_utilizzabile_richiede_pseudonimizzazione_e_accettazione(documento):
    # Accettato ma non pseudonimizzato -> NON utilizzabile (vincolo §119).
    documento.stato_accettazione = Documento.StatoAccettazione.ACCETTATO_SENZA_VERIFICA
    assert documento.utilizzabile is False
    documento.pseudonimizzato = True
    assert documento.utilizzabile is True


def test_accetta_rifiutato_se_non_pseudonimizzato(documento):
    client = APIClient()
    client.force_authenticate(user=documento.sezione.lavoro.utente)
    resp = client.post(f"/api/documenti/{documento.id}/accetta/")
    assert resp.status_code == 409
    documento.refresh_from_db()
    assert documento.stato_accettazione == Documento.StatoAccettazione.DA_VERIFICARE


def test_accetta_ok_dopo_pseudonimizzazione(documento):
    documento.pseudonimizzato = True
    documento.save(update_fields=["pseudonimizzato"])
    client = APIClient()
    client.force_authenticate(user=documento.sezione.lavoro.utente)
    resp = client.post(f"/api/documenti/{documento.id}/accetta/")
    assert resp.status_code == 200
    documento.refresh_from_db()
    assert documento.utilizzabile is True


def test_accetta_tutti(documento):
    documento.pseudonimizzato = True
    documento.save(update_fields=["pseudonimizzato"])
    lavoro = documento.sezione.lavoro
    client = APIClient()
    client.force_authenticate(user=lavoro.utente)
    resp = client.post(f"/api/lavori/{lavoro.id}/accetta-tutti/")
    assert resp.status_code == 200
    assert resp.data["accettati"] == 1
    documento.refresh_from_db()
    assert documento.utilizzabile is True
