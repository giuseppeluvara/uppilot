"""Test dell'export .docx (§7)."""
from io import BytesIO

import pytest
from docx import Document as DocxDocument
from rest_framework.test import APIClient

from apps.analisi.export import genera_docx
from apps.analisi.models import Bozza, Richiesta
from apps.casi.models import Lavoro


def _testi(docx_bytes: bytes) -> str:
    doc = DocxDocument(BytesIO(docx_bytes))
    return "\n".join(p.text for p in doc.paragraphs)


@pytest.fixture
def lavoro_completo(db, django_user_model):
    u = django_user_model.objects.create_user(username="r", password="x")
    lavoro = Lavoro.objects.create(utente=u, titolo="Caso Alfa")
    Bozza.objects.create(lavoro=lavoro, in_fatto="Le parti hanno stipulato un contratto.")
    Richiesta.objects.create(
        lavoro=lavoro,
        parte_richiedente=Richiesta.Parte.ATTORE,
        testo="Chiede l'adempimento.",
        onere_probatorio="Spetta all'attore, da confermare.",
        non_contestazioni=["La stipula non è contestata."],
        quesiti_aperti=["L'onere spetta all'attore: confermi?"],
        ordine=0,
    )
    return lavoro


def test_docx_contiene_struttura_e_quesiti(lavoro_completo):
    testo = _testi(genera_docx(lavoro_completo))
    assert "Le parti hanno stipulato un contratto." in testo
    assert "In fatto" in testo
    assert "In diritto" in testo
    assert "Spetta all'attore" in testo
    assert "[DA DECIDERE]" in testo  # quesito discrezionale distinto (§1)
    assert "P.Q.M." in testo


def test_endpoint_download_docx(lavoro_completo):
    client = APIClient()
    client.force_authenticate(user=lavoro_completo.utente)
    resp = client.get(f"/api/lavori/{lavoro_completo.id}/esporta/")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    assert "attachment" in resp["Content-Disposition"]
    assert resp.content[:2] == b"PK"  # i .docx sono archivi zip


def test_export_in_chiaro_sostituisce_i_placeholder(db, django_user_model):
    u = django_user_model.objects.create_user(username="c", password="x")
    lavoro = Lavoro.objects.create(
        utente=u,
        titolo="Caso In Chiaro",
        mappa_entita={"[PRIVATE_PERSON_1]": "Tizio Bianchi"},
    )
    Bozza.objects.create(lavoro=lavoro, in_fatto="Il sig. [PRIVATE_PERSON_1] agisce in giudizio.")

    pseudo = _testi(genera_docx(lavoro, in_chiaro=False))
    chiaro = _testi(genera_docx(lavoro, in_chiaro=True))

    assert "[PRIVATE_PERSON_1]" in pseudo and "Tizio Bianchi" not in pseudo
    assert "Tizio Bianchi" in chiaro and "[PRIVATE_PERSON_1]" not in chiaro
    assert "DATI PERSONALI REALI" in chiaro  # avviso in chiaro


def test_export_include_motivazione_e_pqm(db, django_user_model):
    u = django_user_model.objects.create_user(username="m", password="x")
    lavoro = Lavoro.objects.create(utente=u, titolo="Caso Editor")
    Bozza.objects.create(lavoro=lavoro, in_fatto="Fatto.", pqm="Condanna al pagamento di 100.")
    Richiesta.objects.create(
        lavoro=lavoro,
        parte_richiedente=Richiesta.Parte.ATTORE,
        testo="Chiede X.",
        motivazione="La domanda è fondata perché risulta provata.",
        ordine=0,
    )
    testo = _testi(genera_docx(lavoro))
    assert "La domanda è fondata perché risulta provata." in testo
    assert "Condanna al pagamento di 100." in testo
    assert "[Da compilare dall'operatore]" not in testo


@pytest.mark.django_db
def test_patch_richiesta_motivazione(django_user_model):
    u = django_user_model.objects.create_user(username="m", password="x")
    lavoro = Lavoro.objects.create(utente=u, titolo="Caso")
    r = Richiesta.objects.create(
        lavoro=lavoro, parte_richiedente=Richiesta.Parte.ATTORE, testo="X", ordine=0
    )
    client = APIClient()
    client.force_authenticate(user=u)
    resp = client.patch(f"/api/richieste/{r.id}/", {"motivazione": "Motivazione redatta."}, format="json")
    assert resp.status_code == 200
    r.refresh_from_db()
    assert r.motivazione == "Motivazione redatta."


def test_export_lavoro_altrui_404(lavoro_completo, django_user_model):
    intruso = django_user_model.objects.create_user(username="b", password="x")
    client = APIClient()
    client.force_authenticate(user=intruso)
    resp = client.get(f"/api/lavori/{lavoro_completo.id}/esporta/")
    assert resp.status_code == 404
