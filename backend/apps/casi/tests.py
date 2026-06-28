import pytest
import json
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


@pytest.mark.django_db
def test_eliminazione_lavoro_proprio_rimuove_sezioni(utente):
    lavoro = Lavoro.objects.create(utente=utente, titolo="Da eliminare")
    SezioneDocumenti.objects.create(lavoro=lavoro, tipo=SezioneDocumenti.Tipo.ATTORE)
    client = APIClient()
    client.force_authenticate(user=utente)

    resp = client.delete(f"/api/lavori/{lavoro.id}/")

    assert resp.status_code == 204
    assert not Lavoro.objects.filter(id=lavoro.id).exists()
    assert not SezioneDocumenti.objects.filter(lavoro_id=lavoro.id).exists()


@pytest.mark.django_db
def test_eliminazione_lavoro_altrui_404(utente, django_user_model):
    altro = django_user_model.objects.create_user(username="altro", password="x")
    lavoro = Lavoro.objects.create(utente=altro, titolo="Non mio")
    client = APIClient()
    client.force_authenticate(user=utente)

    resp = client.delete(f"/api/lavori/{lavoro.id}/")

    assert resp.status_code == 404
    assert Lavoro.objects.filter(id=lavoro.id).exists()


@pytest.mark.django_db
def test_crea_fascicolo_demo_civile(utente):
    client = APIClient()
    client.force_authenticate(user=utente)

    resp = client.post("/api/lavori/demo/", {"tipo": "civile"}, format="json")

    assert resp.status_code == 201
    lavoro = Lavoro.objects.get(id=resp.json()["id"])
    assert lavoro.sezioni.count() == 3
    assert lavoro.richieste.count() >= 3
    assert lavoro.analisi_stato == Lavoro.StatoAnalisi.COMPLETATA
    assert lavoro.approfondimento_stato == Lavoro.StatoAnalisi.COMPLETATA
    assert Documento.objects.filter(sezione__lavoro=lavoro, pseudonimizzato=True).count() >= 4


@pytest.mark.django_db
def test_metadata_documento_e_collaborazione_lavoro(utente):
    client = APIClient()
    client.force_authenticate(user=utente)
    lavoro = Lavoro.objects.create(utente=utente, titolo="Caso metadata")
    sezione = SezioneDocumenti.objects.create(lavoro=lavoro, tipo=SezioneDocumenti.Tipo.ATTORE)
    doc = Documento.objects.create(sezione=sezione, file="documenti/x.pdf")

    meta = client.patch(
        f"/api/documenti/{doc.id}/metadata/",
        {"nome_logico": "Atto introduttivo", "tipo_rilevato": "citazione", "ordine": 2},
        format="json",
    )
    assert meta.status_code == 200
    doc.refresh_from_db()
    assert doc.nome_logico == "Atto introduttivo"
    assert doc.tipo_rilevato == "citazione"
    assert doc.ordine == 2

    collab = client.patch(
        f"/api/lavori/{lavoro.id}/collaborazione/",
        {"assegna_a_me": True, "revisore_a_me": True, "stato_revisione": "validato"},
        format="json",
    )
    assert collab.status_code == 200
    lavoro.refresh_from_db()
    assert lavoro.assegnato_a == utente
    assert lavoro.revisore == utente
    assert lavoro.stato_revisione == "validato"


@pytest.mark.django_db
def test_template_provvedimento_e_backup_import(utente):
    client = APIClient()
    client.force_authenticate(user=utente)
    demo = client.post("/api/lavori/demo/", {"tipo": "penale"}, format="json")
    lavoro_id = demo.json()["id"]

    template = client.post(
        f"/api/lavori/{lavoro_id}/template/",
        {"template_id": "penale"},
        format="json",
    )
    assert template.status_code == 200
    lavoro = Lavoro.objects.get(id=lavoro_id)
    assert "imputazione" in lavoro.modello_testo

    backup = client.get(f"/api/lavori/{lavoro_id}/backup/")
    assert backup.status_code == 200
    payload = json.loads(backup.content.decode("utf-8"))
    assert payload["documenti"]
    assert payload["richieste"]
    assert payload["bozza"]

    imported = client.post("/api/lavori/importa-backup/", payload, format="json")
    assert imported.status_code == 201
    nuovo = Lavoro.objects.get(id=imported.json()["id"])
    assert nuovo.richieste.count() == len(payload["richieste"])
    assert Documento.objects.filter(sezione__lavoro=nuovo).count() == len(payload["documenti"])


@pytest.mark.django_db
def test_e2e_demo_civile_penale_revisione_redteam_export(utente):
    client = APIClient()
    client.force_authenticate(user=utente)

    for tipo in ("civile", "penale"):
        demo = client.post("/api/lavori/demo/", {"tipo": tipo}, format="json")
        assert demo.status_code == 201
        lavoro_id = demo.json()["id"]

        revisione = client.get(f"/api/lavori/{lavoro_id}/revisione/")
        matrice = client.get(f"/api/lavori/{lavoro_id}/matrice/")
        redteam = client.post(f"/api/lavori/{lavoro_id}/red-team/", {}, format="json")
        export = client.get(f"/api/lavori/{lavoro_id}/esporta/")
        audit = client.get(f"/api/lavori/{lavoro_id}/audit/")

        assert revisione.status_code == 200
        assert revisione.json()["dashboard"]["domande"]
        assert revisione.json()["qualita_ai"]["richieste_totali"] >= 3
        assert matrice.status_code == 200
        assert len(matrice.json()) >= 3
        assert redteam.status_code == 200
        assert "conteggi" in redteam.json()
        assert export.status_code == 200
        assert export.content[:2] == b"PK"
        assert audit.status_code == 200
        assert audit.content[:2] == b"PK"
