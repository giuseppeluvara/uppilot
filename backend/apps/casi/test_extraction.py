"""Test dell'estrazione testo (PDF nativo vs OCR) e dell'upload."""
import fitz  # PyMuPDF
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from ai.interfaces import OCRResult
from apps.casi.models import Documento, Lavoro, SezioneDocumenti
from apps.casi.services.extraction import estrai_testo


class FakeOCR:
    """OCRBackend finto: restituisce un testo prefissato senza chiamare Ollama."""

    def __init__(self, testo="TESTO DA OCR", passaggi_incerti=None):
        self.testo = testo
        self.passaggi_incerti = passaggi_incerti or []
        self.chiamato = False

    def recognize(self, image: bytes, mode: str = "text") -> OCRResult:
        self.chiamato = True
        return OCRResult(testo=self.testo, passaggi_incerti=self.passaggi_incerti)


def _pdf_con_testo(path, testo):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), testo)
    doc.save(str(path))
    doc.close()


def _pdf_vuoto(path):
    doc = fitz.open()
    doc.new_page()  # pagina senza testo selezionabile (simula scansione)
    doc.save(str(path))
    doc.close()


def _png_vuoto(path):
    doc = fitz.open()
    page = doc.new_page()
    page.get_pixmap(dpi=72).save(str(path))
    doc.close()


def test_pdf_nativo_estrazione_diretta(tmp_path):
    pdf = tmp_path / "atto.pdf"
    _pdf_con_testo(pdf, "Atto di citazione: domanda di risarcimento.")
    ocr = FakeOCR()

    res = estrai_testo(str(pdf), "atto.pdf", ocr)

    assert res.metodo == "pdf_nativo"
    assert "risarcimento" in res.testo
    assert ocr.chiamato is False  # niente OCR sui PDF nativi (§108)


def test_pdf_scansione_va_in_ocr(tmp_path):
    pdf = tmp_path / "scansione.pdf"
    _pdf_vuoto(pdf)
    ocr = FakeOCR(testo="testo riconosciuto dalla scansione")

    res = estrai_testo(str(pdf), "scansione.pdf", ocr)

    assert res.metodo == "glm_ocr"
    assert ocr.chiamato is True
    assert "riconosciuto" in res.testo


def test_immagine_va_in_ocr(tmp_path):
    img = tmp_path / "doc.png"
    _png_vuoto(img)
    ocr = FakeOCR(testo="testo da immagine")

    res = estrai_testo(str(img), "doc.png", ocr)

    assert res.metodo == "glm_ocr"
    assert res.testo == "testo da immagine"


def test_ocr_vuoto_segnala_bassa_confidenza(tmp_path):
    img = tmp_path / "manoscritto.png"
    _png_vuoto(img)
    ocr = FakeOCR(testo="")  # nessun testo affidabile

    res = estrai_testo(str(img), "manoscritto.png", ocr)

    assert res.flag_bassa_confidenza is True
    assert res.passaggi_incerti  # passaggio marcato per la verifica (§111)


def test_ocr_output_degenere_segnala_bassa_confidenza(tmp_path):
    # GLM-OCR su immagine illeggibile emette solo code-fence vuoti: va flaggato.
    img = tmp_path / "illeggibile.png"
    _png_vuoto(img)
    ocr = FakeOCR(testo="```markdown\n\n```markdown\n\n```text\n```")

    res = estrai_testo(str(img), "illeggibile.png", ocr)

    assert res.flag_bassa_confidenza is True
    assert res.passaggi_incerti


@pytest.mark.django_db
def test_upload_documento_avvia_estrazione(django_user_model, monkeypatch):
    # La catena include la pseudonimizzazione: mock del servizio (niente HTTP reale).
    from ai.interfaces import AnonymizationResult

    monkeypatch.setattr(
        "apps.casi.tasks.get_anonymization_service",
        lambda: type(
            "S", (), {"anonymize": lambda self, t: AnonymizationResult(t, {})}
        )(),
    )
    utente = django_user_model.objects.create_user(username="r", password="x")
    lavoro = Lavoro.objects.create(utente=utente, titolo="Caso")
    sezione = SezioneDocumenti.objects.create(
        lavoro=lavoro, tipo=SezioneDocumenti.Tipo.ATTORE
    )

    # Costruisce un PDF nativo in memoria.
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Comparsa di costituzione del convenuto.")
    pdf_bytes = doc.tobytes()
    doc.close()

    client = APIClient()
    client.force_authenticate(user=utente)
    upload = SimpleUploadedFile("comparsa.pdf", pdf_bytes, content_type="application/pdf")
    resp = client.post(
        "/api/documenti/", {"sezione": sezione.id, "file": upload}, format="multipart"
    )
    assert resp.status_code == 201

    # Con CELERY_TASK_ALWAYS_EAGER l'intera catena è già avvenuta (PDF nativo).
    documento = Documento.objects.get(id=resp.data["id"])
    assert documento.stato_estrazione == Documento.StatoEstrazione.COMPLETATO
    assert documento.metodo_estrazione == Documento.MetodoEstrazione.PDF_NATIVO
    assert "convenuto" in documento.testo_estratto
    # La pseudonimizzazione è stata eseguita subito dopo (§119).
    assert documento.pseudonimizzato is True


@pytest.mark.django_db
def test_upload_su_sezione_altrui_vietato(django_user_model):
    proprietario = django_user_model.objects.create_user(username="a", password="x")
    intruso = django_user_model.objects.create_user(username="b", password="x")
    lavoro = Lavoro.objects.create(utente=proprietario, titolo="Caso")
    sezione = SezioneDocumenti.objects.create(
        lavoro=lavoro, tipo=SezioneDocumenti.Tipo.ATTORE
    )

    client = APIClient()
    client.force_authenticate(user=intruso)
    upload = SimpleUploadedFile("x.pdf", b"%PDF-1.4", content_type="application/pdf")
    resp = client.post(
        "/api/documenti/", {"sezione": sezione.id, "file": upload}, format="multipart"
    )
    assert resp.status_code == 400  # sezione non accessibile
