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


def test_endpoint_export_ripara_placeholder_malformed_prima_del_privacy_check(db, django_user_model):
    u = django_user_model.objects.create_user(username="repair", password="x")
    lavoro = Lavoro.objects.create(
        utente=u,
        titolo="UPP AUDIT 2026-06-28 - Civile appalto complesso",
        mappa_entita={"[ORGANIZZAZIONE_1]": "Aurora Impianti S.r.l."},
    )
    Bozza.objects.create(
        lavoro=lavoro,
        in_fatto="[organizzazione_1] ha stipulato il contratto.",
        pqm="Rigetta o accoglie secondo prova.",
    )
    Richiesta.objects.create(
        lavoro=lavoro,
        parte_richiedente=Richiesta.Parte.ATTORE,
        testo="[organizzazione_1] chiede la condanna.",
        motivazione="[organizzazione_1] ha prodotto una fonte interna sufficiente.",
        ordine=0,
    )
    client = APIClient()
    client.force_authenticate(user=u)

    resp = client.get(f"/api/lavori/{lavoro.id}/esporta/")

    assert resp.status_code == 200
    testo = _testi(resp.content)
    assert "[ORGANIZZAZIONE_1]" in testo
    assert "[organizzazione_1]" not in testo
    assert "Aurora Impianti" not in testo


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


def test_export_pseudonimizzato_non_usa_titolo_reale_o_residui(db, django_user_model):
    u = django_user_model.objects.create_user(username="p", password="x")
    lavoro = Lavoro.objects.create(
        utente=u,
        titolo="Causa Tizio Bianchi",
        mappa_entita={"[PRIVATE_PERSON_1]": "Tizio Bianchi"},
    )
    Bozza.objects.create(
        lavoro=lavoro,
        in_fatto="Tizio Bianchi agisce contro [PRIVATE_PERSON_1].",
    )

    pseudo = _testi(genera_docx(lavoro, in_chiaro=False))
    chiaro = _testi(genera_docx(lavoro, in_chiaro=True))

    assert f"Fascicolo #{lavoro.id}" in pseudo
    assert "Causa Tizio Bianchi" not in pseudo
    assert "Tizio" not in pseudo and "Bianchi" not in pseudo
    assert "[PRIVATE_PERSON_1]" in pseudo
    assert "Causa Tizio Bianchi" in chiaro


def test_export_include_motivazione_e_pqm(db, django_user_model):
    u = django_user_model.objects.create_user(username="m", password="x")
    lavoro = Lavoro.objects.create(utente=u, titolo="Caso Editor")
    Bozza.objects.create(lavoro=lavoro, in_fatto="Fatto.", pqm="Condanna al pagamento di 100.")
    Richiesta.objects.create(
        lavoro=lavoro,
        parte_richiedente=Richiesta.Parte.ATTORE,
        testo="Chiede X.",
        motivazione="La domanda è fondata perché risulta provata.",
        fonti_tracciate=[
            {
                "documento_id": 10,
                "documento_nome": "atto.pdf",
                "score": 0.82,
                "affidabilita_label": "Riscontro forte",
                "snippet": "Snippet pseudonimizzato a supporto della domanda.",
            }
        ],
        ordine=0,
    )
    testo = _testi(genera_docx(lavoro))
    assert "La domanda è fondata perché risulta provata." in testo
    assert "Condanna al pagamento di 100." in testo
    assert "Fonti interne tracciate" in testo
    assert "Snippet pseudonimizzato" in testo
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
