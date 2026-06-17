"""Estrazione testo dai documenti (§107-111).

Strategia:
- PDF con testo selezionabile (PCT nativo) -> estrazione DIRETTA, niente OCR.
- PDF scansionato / immagine / manoscritto -> rasterizzazione pagina->immagine
  poi GLM-OCR (via OCRBackend).

Segnalazione di mala lettura (§111): i passaggi dubbi vengono marcati e il
documento riceve `flag_bassa_confidenza` perché l'utente verifichi.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import fitz  # PyMuPDF

from ai.interfaces import OCRBackend

logger = logging.getLogger(__name__)

# Soglia: se il testo selezionabile medio per pagina è sotto questo valore,
# il PDF è verosimilmente una scansione -> serve OCR.
_SOGLIA_CARATTERI_PER_PAGINA = 20

_ESTENSIONI_IMMAGINE = (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp")

# Parametri di rasterizzazione per l'OCR. GLM-OCR via Ollama degrada su immagini
# troppo grandi (vengono ridimensionate e diventano illeggibili): manteniamo un
# DPI moderato e un cap sul lato massimo, RGB senza canale alpha, output JPEG.
_OCR_DPI = 150
_OCR_LATO_MAX = 1800


def _pixmap_a_jpeg(pix: "fitz.Pixmap") -> bytes:
    """Normalizza un pixmap per l'OCR: RGB, senza alpha, ridotto se troppo grande."""
    if pix.alpha:
        pix = fitz.Pixmap(pix, 0)  # rimuove il canale alpha
    if pix.colorspace is None or pix.colorspace.name != fitz.csRGB.name:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    while max(pix.width, pix.height) > _OCR_LATO_MAX:
        pix.shrink(1)  # dimezza le dimensioni finché rientra nel cap
    return pix.tobytes("jpg", jpg_quality=95)


@dataclass
class RisultatoEstrazione:
    metodo: str  # valore di Documento.MetodoEstrazione
    testo: str
    flag_bassa_confidenza: bool = False
    passaggi_incerti: list[str] | None = None

    def __post_init__(self):
        if self.passaggi_incerti is None:
            self.passaggi_incerti = []


def _pdf_ha_testo_selezionabile(doc: "fitz.Document") -> tuple[bool, str]:
    """Estrae il testo nativo e decide se il PDF è 'nativo' o una scansione."""
    parti = [pagina.get_text("text") for pagina in doc]
    testo = "\n".join(parti).strip()
    caratteri_utili = len(testo.replace("\n", "").replace(" ", ""))
    media = caratteri_utili / max(len(doc), 1)
    return media >= _SOGLIA_CARATTERI_PER_PAGINA, testo


def _testo_significativo(testo: str) -> str:
    """Rimuove marcatori markdown e spazi per valutare se c'è testo reale.

    GLM-OCR su immagini illeggibili tende a emettere solo code-fence vuoti
    (es. ```markdown ... ```): vanno trattati come 'nessun testo'.
    """
    ripulito = testo.replace("`", "").replace("markdown", "").replace("text", "")
    return ripulito.strip()


def _ocr_immagine(ocr: OCRBackend, image_bytes: bytes, etichetta: str):
    """Esegue l'OCR su una singola immagine e ne valuta la confidenza."""
    risultato = ocr.recognize(image_bytes, mode="text")
    incerti: list[str] = list(risultato.passaggi_incerti)
    bassa = risultato.bassa_confidenza
    # Euristica di sicurezza: output vuoto/degenere = lettura dubbia (§111).
    if len(_testo_significativo(risultato.testo)) < 3:
        bassa = True
        incerti.append(f"{etichetta}: nessun testo affidabile estratto")
    return risultato.testo, bassa, incerti


def _ocr_pdf(ocr: OCRBackend, doc: "fitz.Document") -> RisultatoEstrazione:
    testi: list[str] = []
    incerti: list[str] = []
    bassa = False
    for i, pagina in enumerate(doc, start=1):
        # Rasterizza la pagina e normalizza l'immagine per l'OCR.
        pix = pagina.get_pixmap(dpi=_OCR_DPI, colorspace=fitz.csRGB, alpha=False)
        testo, pagina_bassa, pagina_incerti = _ocr_immagine(
            ocr, _pixmap_a_jpeg(pix), f"pagina {i}"
        )
        testi.append(testo)
        incerti.extend(pagina_incerti)
        bassa = bassa or pagina_bassa
    return RisultatoEstrazione(
        metodo="glm_ocr",
        testo="\n\n".join(testi).strip(),
        flag_bassa_confidenza=bassa,
        passaggi_incerti=incerti,
    )


def estrai_testo(file_path: str, nome_file: str, ocr: OCRBackend) -> RisultatoEstrazione:
    """Estrae il testo da un file, scegliendo PDF nativo vs OCR.

    `ocr` è iniettato (l'OCRBackend dalla factory) per restare testabile.
    """
    nome = nome_file.lower()

    if nome.endswith(".pdf"):
        with fitz.open(file_path) as doc:
            ha_testo, testo = _pdf_ha_testo_selezionabile(doc)
            if ha_testo:
                return RisultatoEstrazione(metodo="pdf_nativo", testo=testo)
            logger.info("PDF senza testo selezionabile: passo a OCR (%s)", nome_file)
            return _ocr_pdf(ocr, doc)

    if nome.endswith(_ESTENSIONI_IMMAGINE):
        # Normalizza l'immagine caricata (RGB, no alpha, cap dimensione) per l'OCR.
        immagine = _pixmap_a_jpeg(fitz.Pixmap(file_path))
        testo, bassa, incerti = _ocr_immagine(ocr, immagine, "immagine")
        return RisultatoEstrazione(
            metodo="glm_ocr",
            testo=testo,
            flag_bassa_confidenza=bassa,
            passaggi_incerti=incerti,
        )

    raise ValueError(f"Tipo di file non supportato per l'estrazione: {nome_file}")
