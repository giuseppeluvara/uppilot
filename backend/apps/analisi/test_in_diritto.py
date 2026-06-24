"""Test del ragionamento 'in diritto' per richiesta (M2) con LLM mockato."""
import json

import pytest
from rest_framework.test import APIClient

from apps.analisi import tasks
from apps.analisi.models import Bozza, Richiesta
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
            "motivazione": "La domanda richiede verifica del contratto prodotto.",
            "allegati": [doc.id, 9999],  # 9999 non esiste -> deve essere scartato
            "non_contestazioni": ["La stipula non è contestata."],
            "quesiti_aperti": ["L'onere spetta all'attore: confermi?"],
        }
    )

    dati = approfondisci_richiesta(richiesta, [doc], llm)

    assert dati["allegati"] == [doc.id]
    assert dati["motivazione"].startswith("La domanda")
    assert "[PRIVATE_PERSON_1]" in llm.ultimo_prompt
    assert "ORIGINALE" not in llm.ultimo_prompt
    assert f"Documento {doc.id}" in llm.ultimo_prompt
    assert llm.ultimi_opts.get("format") == "json"
    assert llm.ultimi_opts.get("think") is False


def test_task_popola_richiesta_e_stato(scenario, monkeypatch):
    lavoro, doc, richiesta = scenario
    payload = {
        "onere_probatorio": "Onere a carico dell'attore.",
        "motivazione": "La domanda va valutata sulla base del contratto.",
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
    assert richiesta.motivazione.startswith("La domanda")
    assert list(richiesta.allegati_collegati.values_list("id", flat=True)) == [doc.id]
    assert richiesta.quesiti_aperti  # discrezionale come quesito (§1)
    bozza = Bozza.objects.get(lavoro=lavoro)
    contenuto = bozza.contenuto_per_richiesta[str(richiesta.id)]
    assert contenuto["motivazione"] == richiesta.motivazione
    assert contenuto["allegati_collegati"] == [doc.id]
    assert bozza.pqm


def test_approfondisci_corregge_onere_penale_ritardo(scenario):
    lavoro, doc, _ = scenario
    richiesta = Richiesta.objects.create(
        lavoro=lavoro,
        parte_richiedente=Richiesta.Parte.CONVENUTO,
        tipo=Richiesta.Tipo.DOMANDA,
        testo="Applicare la penale contrattuale di euro 3.000 per dodici giorni di ritardo.",
        ordine=1,
    )
    llm = FakeLLM(
        {
            "onere_probatorio": "Al convenuto spetta provare la non imputabilità del ritardo stesso.",
            "motivazione": "La penale richiede verifica del ritardo.",
            "allegati": [doc.id],
            "non_contestazioni": [],
            "quesiti_aperti": [],
        }
    )

    dati = approfondisci_richiesta(richiesta, [doc], llm)

    assert "non imputabilità del ritardo stesso" not in dati["onere_probatorio"]
    assert "clausola penale" in dati["onere_probatorio"]
    assert "imputabilita' del ritardo alla controparte" in dati["onere_probatorio"]


def test_approfondisci_rimpiazza_onere_contaminato_da_altri_capi(scenario):
    lavoro, doc, richiesta = scenario
    richiesta.testo = "Condannare il convenuto al pagamento di euro 28.600."
    richiesta.tipo = Richiesta.Tipo.DOMANDA
    richiesta.save(update_fields=["testo", "tipo"])
    llm = FakeLLM(
        {
            "onere_probatorio": (
                "All'attore spetta provare il credito, la penale contrattuale "
                "di euro 3.000 e i costi di ripristino di euro 18.900."
            ),
            "motivazione": "La domanda richiede verifica del credito.",
            "allegati": [doc.id],
            "non_contestazioni": [],
            "quesiti_aperti": [],
        }
    )

    dati = approfondisci_richiesta(richiesta, [doc], llm)

    assert "penale contrattuale" not in dati["onere_probatorio"]
    assert "18.900" not in dati["onere_probatorio"]
    assert "fatti costitutivi della pretesa" in dati["onere_probatorio"]


def test_approfondisci_rimpiazza_onere_istruttorio_fuori_fuoco(scenario):
    lavoro, doc, richiesta = scenario
    richiesta.testo = "Disporre CTU tecnica sull'origine delle infiltrazioni."
    richiesta.tipo = Richiesta.Tipo.ISTRUTTORIA
    richiesta.save(update_fields=["testo", "tipo"])
    llm = FakeLLM(
        {
            "onere_probatorio": "All'attore spetta provare il pagamento della fattura.",
            "motivazione": "La CTU va valutata in relazione ai fatti controversi.",
            "allegati": [doc.id],
            "non_contestazioni": [],
            "quesiti_aperti": [],
        }
    )

    dati = approfondisci_richiesta(richiesta, [doc], llm)

    assert "mezzo istruttorio" in dati["onere_probatorio"]
    assert "ammissibilita'" in dati["onere_probatorio"]


def test_approfondisci_rimpiazza_onere_con_fattura_estranea(scenario):
    lavoro, doc, richiesta = scenario
    richiesta.testo = "Rigettare le contestazioni sulle infiltrazioni estranee all'appalto."
    richiesta.tipo = Richiesta.Tipo.DIFESA_ECCEZIONE
    richiesta.save(update_fields=["testo", "tipo"])
    llm = FakeLLM(
        {
            "onere_probatorio": "All'attore spetta provare la non contestazione della fattura n. [PRIVATE_DATE_4].",
            "motivazione": "La difesa richiede verifica tecnica sulle infiltrazioni.",
            "allegati": [doc.id],
            "non_contestazioni": [],
            "quesiti_aperti": [],
        }
    )

    dati = approfondisci_richiesta(richiesta, [doc], llm)

    assert "fattura" not in dati["onere_probatorio"]
    assert "difesa o eccezione" in dati["onere_probatorio"]


def test_approfondisci_motivazione_fallback_e_non_contestazione_prudente(scenario):
    lavoro, doc, richiesta = scenario
    convenuto = _doc(
        lavoro,
        SezioneDocumenti.Tipo.CONVENUTO,
        "Il convenuto contesta l'inadempimento e l'origine delle infiltrazioni.",
    )
    llm = FakeLLM(
        {
            "onere_probatorio": "Onere da confermare.",
            "allegati": [doc.id, convenuto.id],
            "non_contestazioni": ["L'estraneità delle infiltrazioni all'appalto è ammessa da entrambe le parti"],
            "quesiti_aperti": [],
        }
    )

    dati = approfondisci_richiesta(richiesta, [doc, convenuto], llm)

    assert dati["motivazione"]
    assert dati["non_contestazioni"] == []
    assert any("davvero non contestato" in q for q in dati["quesiti_aperti"])


def test_endpoint_approfondisci(scenario, monkeypatch):
    lavoro, doc, richiesta = scenario
    monkeypatch.setattr(
        tasks,
        "get_llm_backend",
        lambda *a, **k: FakeLLM({"onere_probatorio": "x", "motivazione": "m", "allegati": [], "non_contestazioni": [], "quesiti_aperti": []}),
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
