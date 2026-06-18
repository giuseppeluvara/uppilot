"""Generazione della bozza in formato Word (.docx) — §7.

Struttura (curata, professionale): intestazione, "In fatto", "In diritto"
(motivazione per ciascuna domanda con onere probatorio, non contestazioni,
allegati e quesiti), P.Q.M.

Lo stile tipografico è definito nel CODICE (font, gerarchia, giustificazione,
riquadri) così da essere versionabile e riproducibile. Resta il gancio per un
template.docx fornito dall'utente: se presente, si rispetta quello.

Principio §1: i punti discrezionali restano quesiti, riportati come callout
"Da decidere — verifica tu" visivamente distinti — mai conclusioni definitive.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from django.conf import settings
from docx import Document as DocxDocument
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from .models import Bozza

_PARTE_LABEL = {"attore": "attore", "convenuto": "convenuto/ricorrente"}

_FONT = "Times New Roman"
_ACCENTO = RGBColor(0x1F, 0x3A, 0x5F)  # blu ardesia sobrio (unico accento)
_QUESITO_FILL = "FFF3CD"  # ambra chiaro per i callout "Da decidere"
_QUESITO_BORDO = "E0A800"
_QUESITO_LABEL = RGBColor(0x8A, 0x6D, 0x3B)
_AVVISO_FILL = "F1F1F1"
_ROSSO = RGBColor(0xB0, 0x00, 0x20)


def _nome_file(percorso: str) -> str:
    return percorso.split("/")[-1]


def _documento_base() -> tuple["DocxDocument", bool]:
    """Usa template.docx dei sample se presente; restituisce (doc, da_template)."""
    template: Path = settings.SAMPLE_OUTPUT_DIR / "template.docx"
    if template.exists():
        return DocxDocument(str(template)), True
    return DocxDocument(), False


def _ombreggia(paragrafo, fill_hex: str) -> None:
    """Imposta lo sfondo (shading) di un paragrafo."""
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    paragrafo._p.get_or_add_pPr().append(shd)


def _bordo_sinistro(paragrafo, color_hex: str) -> None:
    """Aggiunge una barra di bordo a sinistra (effetto callout)."""
    pPr = paragrafo._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "18")
    left.set(qn("w:space"), "8")
    left.set(qn("w:color"), color_hex)
    pbdr.append(left)
    pPr.append(pbdr)


def _assicura_stile_quesito(doc) -> None:
    if "Quesito" not in [s.name for s in doc.styles]:
        st = doc.styles.add_style("Quesito", WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = doc.styles["Normal"]
        st.font.size = Pt(11)
        st.font.italic = True
        st.paragraph_format.left_indent = Pt(12)
        st.paragraph_format.space_before = Pt(4)
        st.paragraph_format.space_after = Pt(4)


def _applica_stili(doc) -> None:
    """Stile professionale: corpo serif giustificato, gerarchia titoli con accento."""
    normal = doc.styles["Normal"]
    normal.font.name = _FONT
    normal.font.size = Pt(12)
    pf = normal.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.space_after = Pt(6)
    pf.line_spacing = 1.3

    for nome, dim in (("Title", 20), ("Heading 1", 14), ("Heading 2", 12.5)):
        st = doc.styles[nome]
        st.font.name = _FONT
        st.font.size = Pt(dim)
        st.font.bold = True
        st.font.color.rgb = _ACCENTO
    h1 = doc.styles["Heading 1"].paragraph_format
    h1.space_before = Pt(14)
    h1.space_after = Pt(4)


def _numeri_pagina(doc) -> None:
    """Footer centrato con numero di pagina."""
    footer = doc.sections[0].footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run("Pag. ")
    run = p.add_run()
    inizio = OxmlElement("w:fldChar")
    inizio.set(qn("w:fldCharType"), "begin")
    istr = OxmlElement("w:instrText")
    istr.set(qn("xml:space"), "preserve")
    istr.text = "PAGE"
    fine = OxmlElement("w:fldChar")
    fine.set(qn("w:fldCharType"), "end")
    run._r.append(inizio)
    run._r.append(istr)
    run._r.append(fine)


def _depseudonimizza(testo: str, mappa: dict) -> str:
    """Ri-sostituisce i placeholder canonici con i valori reali (export in chiaro)."""
    if not testo or not mappa:
        return testo
    # Placeholder più lunghi prima, per evitare collisioni di prefisso.
    for ph in sorted(mappa, key=len, reverse=True):
        testo = testo.replace(ph, mappa[ph])
    return testo


def genera_docx(lavoro, in_chiaro: bool = False) -> bytes:
    doc, da_template = _documento_base()
    if not da_template:
        _applica_stili(doc)
    _assicura_stile_quesito(doc)

    # In chiaro: registro entità a livello di lavoro; altrimenti nessuna sostituzione.
    mappa = lavoro.mappa_entita if in_chiaro else {}

    def chiaro(t):
        return _depseudonimizza(t, mappa)

    # --- Intestazione ---
    titolo = doc.add_paragraph("BOZZA DI PROVVEDIMENTO", style="Title")
    titolo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_sub = sub.add_run(chiaro(lavoro.titolo))
    run_sub.italic = True

    avviso = doc.add_paragraph()
    _ombreggia(avviso, _AVVISO_FILL)
    nota = avviso.add_run(
        "Bozza assistita, soggetta a revisione umana. I passaggi contrassegnati "
        "[DA DECIDERE] richiedono la valutazione dell'operatore."
    )
    nota.italic = True
    nota.font.size = Pt(10)
    if in_chiaro:
        warn = avviso.add_run(
            " ATTENZIONE: questo documento contiene i DATI PERSONALI REALI delle parti "
            "(versione in chiaro). Trattare con le dovute cautele."
        )
        warn.italic = True
        warn.bold = True
        warn.font.size = Pt(10)
        warn.font.color.rgb = _ROSSO

    # --- In fatto ---
    doc.add_heading("In fatto", level=1)
    bozza = Bozza.objects.filter(lavoro=lavoro).first()
    doc.add_paragraph(chiaro(bozza.in_fatto) if bozza and bozza.in_fatto else "—")

    # --- In diritto (motivazione per ciascuna domanda) ---
    doc.add_heading("In diritto", level=1)
    richieste = list(lavoro.richieste.all())
    if not richieste:
        doc.add_paragraph("Nessuna richiesta analizzata.")
    for i, r in enumerate(richieste, start=1):
        parte = _PARTE_LABEL.get(r.parte_richiedente, r.parte_richiedente)
        doc.add_heading(f"{i}. Domanda di parte {parte}", level=2)
        doc.add_paragraph(chiaro(r.testo))

        if r.motivazione:
            doc.add_paragraph(chiaro(r.motivazione))

        if r.onere_probatorio:
            p = doc.add_paragraph()
            p.add_run("Onere probatorio: ").bold = True
            p.add_run(chiaro(r.onere_probatorio))

        if r.non_contestazioni:
            p = doc.add_paragraph()
            p.add_run("Non contestazioni:").bold = True
            for nc in r.non_contestazioni:
                doc.add_paragraph(chiaro(str(nc)), style="List Bullet")

        allegati = list(r.allegati_collegati.all())
        if allegati:
            p = doc.add_paragraph()
            p.add_run("Allegati collegati: ").bold = True
            p.add_run(", ".join(_nome_file(a.file.name) for a in allegati))

        for q in r.quesiti_aperti:
            qp = doc.add_paragraph(style="Quesito")
            _ombreggia(qp, _QUESITO_FILL)
            _bordo_sinistro(qp, _QUESITO_BORDO)
            label = qp.add_run("Da decidere — verifica tu: ")
            label.bold = True
            label.font.color.rgb = _QUESITO_LABEL
            qp.add_run(chiaro(q))

    # --- P.Q.M. ---
    doc.add_heading("P.Q.M.", level=1)
    if bozza and bozza.pqm:
        doc.add_paragraph(chiaro(bozza.pqm))
    else:
        doc.add_paragraph("[Da compilare dall'operatore]")

    if not da_template:
        _numeri_pagina(doc)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
