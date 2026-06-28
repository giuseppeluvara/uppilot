"""Test del blocco privacy: pseudonimizzazione e flusso di accettazione (§119/§122)."""
import pytest
from rest_framework.test import APIClient

from ai.interfaces import AnonymizationResult
from apps.casi.models import Documento, Lavoro, SezioneDocumenti
from apps.casi import tasks
from apps.casi.privacy import maschera_residui, privacy_report


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


def test_canonicalizzazione_cross_documento_e_residui(db, django_user_model, monkeypatch):
    utente = django_user_model.objects.create_user(username="canon", password="x")
    lavoro = Lavoro.objects.create(utente=utente, titolo="Causa Alfa")
    sezione = SezioneDocumenti.objects.create(
        lavoro=lavoro, tipo=SezioneDocumenti.Tipo.ATTORE
    )
    doc1 = Documento.objects.create(
        sezione=sezione,
        file="a.pdf",
        testo_estratto="Alfa Srl e Paolo Neri.",
        stato_estrazione=Documento.StatoEstrazione.COMPLETATO,
    )
    doc2 = Documento.objects.create(
        sezione=sezione,
        file="b.pdf",
        testo_estratto="Alfa Costruzioni S.r.l.",
        stato_estrazione=Documento.StatoEstrazione.COMPLETATO,
    )
    risultati = [
        AnonymizationResult(
            "[ORG_1] agisce contro Paolo Neri.",
            {"[ORG_1]": "Alfa S.r.l.", "[PERSON_1]": "Paolo Neri"},
        ),
        AnonymizationResult(
            "[ORG_1] deposita memoria.",
            {"[ORG_1]": "Alfa Costruzioni S.r.l."},
        ),
    ]

    monkeypatch.setattr(
        tasks,
        "get_anonymization_service",
        lambda: type("S", (), {"anonymize": lambda self, t: risultati.pop(0)})(),
    )

    tasks.pseudonimizza_documento(doc1.id)
    tasks.pseudonimizza_documento(doc2.id)

    doc1.refresh_from_db()
    doc2.refresh_from_db()
    lavoro.refresh_from_db()
    assert "[ORG_1]" in doc1.mappa_entita
    assert "[ORG_1]" in doc2.mappa_entita
    assert "Paolo" not in doc1.testo_pseudonimizzato
    assert "Neri" not in doc1.testo_pseudonimizzato
    assert len([ph for ph, reale in lavoro.mappa_entita.items() if "Alfa" in reale]) == 1


def test_pseudonimizzazione_maschera_pii_sconosciuti_e_org_italiano(db, django_user_model, monkeypatch):
    utente = django_user_model.objects.create_user(username="privacy", password="x")
    lavoro = Lavoro.objects.create(utente=utente, titolo="Caso")
    sezione = SezioneDocumenti.objects.create(lavoro=lavoro, tipo=SezioneDocumenti.Tipo.CONVENUTO)
    doc = Documento.objects.create(
        sezione=sezione,
        file="c.pdf",
        testo_estratto="Comparsa",
        stato_estrazione=Documento.StatoEstrazione.COMPLETATO,
    )

    monkeypatch.setattr(
        tasks,
        "get_anonymization_service",
        lambda: type(
            "S",
            (),
            {
                "anonymize": lambda self, t: AnonymizationResult(
                    "Il Condominio Beta, rappresentato dall'avv. Paolo Rizzi, contesta [ORGANIZZAZIONE_1].",
                    {"[ORGANIZZAZIONE_1]": "Aurora Impianti S.r.l."},
                )
            },
        )(),
    )

    tasks.pseudonimizza_documento(doc.id)

    doc.refresh_from_db()
    assert "Condominio Beta" not in doc.testo_pseudonimizzato
    assert "Paolo Rizzi" not in doc.testo_pseudonimizzato
    assert any(v == "Condominio Beta" for v in doc.mappa_entita.values())
    assert any(v == "Paolo Rizzi" for v in doc.mappa_entita.values())


def test_pseudonimizzazione_ripara_date_e_indirizzi_spezzati(db, django_user_model, monkeypatch):
    utente = django_user_model.objects.create_user(username="frammenti", password="x")
    lavoro = Lavoro.objects.create(utente=utente, titolo="Caso")
    sezione = SezioneDocumenti.objects.create(lavoro=lavoro, tipo=SezioneDocumenti.Tipo.GENERICI)
    doc = Documento.objects.create(
        sezione=sezione,
        file="d.pdf",
        testo_estratto="Contratto",
        stato_estrazione=Documento.StatoEstrazione.COMPLETATO,
    )

    monkeypatch.setattr(
        tasks,
        "get_anonymization_service",
        lambda: type(
            "S",
            (),
            {
                "anonymize": lambda self, t: AnonymizationResult(
                    "sito in Genova, via Lan [PRIVATE_ADDRESS_1] 7, in data [PRIVATE_DATE_1] 5.",
                    {"[PRIVATE_ADDRESS_1]": "terna", "[PRIVATE_DATE_1]": "20 maggio 202"},
                )
            },
        )(),
    )

    tasks.pseudonimizza_documento(doc.id)

    doc.refresh_from_db()
    assert "Lan [PRIVATE_ADDRESS_1]" not in doc.testo_pseudonimizzato
    assert doc.mappa_entita["[PRIVATE_ADDRESS_1]"] == "Lanterna"
    assert "[PRIVATE_DATE_1] 5" not in doc.testo_pseudonimizzato
    assert doc.mappa_entita["[PRIVATE_DATE_1]"] == "20 maggio 2025"


def test_placeholder_malformed_riparato_e_marker_da_decidere_ammesso():
    mappa = {"[ORGANIZZAZIONE_1]": "Aurora Impianti S.r.l."}
    testo = maschera_residui(
        "[ORGANIZZAZIONIONE_1] chiede [DA DECIDERE]. [organizzazione_1] resiste.",
        mappa,
    )
    assert "[ORGANIZZAZIONE_1]" in testo
    assert "[organizzazione_1]" not in testo
    report = privacy_report(testo, mappa)
    assert report["malformed_placeholders"] == []


def test_privacy_report_extra_values_ignora_titoli_descrittivi():
    report = privacy_report(
        "La bozza tratta appalto, penale e truffa come categorie giuridiche.",
        {},
        extra_values=[
            "UPP AUDIT 2026-06-28 - Civile appalto complesso",
            "UPP AUDIT 2026-06-28 - Penale appropriazione/truffa",
        ],
    )
    assert report["leaks"] == []


def test_privacy_report_extra_values_controlla_nomi_in_titolo():
    report = privacy_report(
        "La bozza cita Rossi e Bianchi senza placeholder.",
        {},
        extra_values=["Rossi c. Bianchi"],
    )
    assert {leak["token"] for leak in report["leaks"]} == {"rossi", "bianchi"}
