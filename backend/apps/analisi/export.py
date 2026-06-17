"""Generazione della bozza in formato Word (.docx) — §7.

Struttura: intestazione, "In fatto", "In diritto" (motivazione per ciascuna
domanda con onere probatorio, non contestazioni, allegati e quesiti), P.Q.M.

Principio §1: i punti discrezionali restano quesiti, riportati nel documento come
note "[DA DECIDERE]" visivamente distinte — mai conclusioni definitive.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from django.conf import settings
from docx import Document as DocxDocument

from .models import Bozza

_PARTE_LABEL = {"attore": "attore", "convenuto": "convenuto/ricorrente"}


def _nome_file(percorso: str) -> str:
    return percorso.split("/")[-1]


def _documento_base() -> "DocxDocument":
    """Usa template.docx dei sample se presente, altrimenti un documento vuoto."""
    template: Path = settings.SAMPLE_OUTPUT_DIR / "template.docx"
    if template.exists():
        return DocxDocument(str(template))
    return DocxDocument()


def _depseudonimizza(testo: str, mappa: dict) -> str:
    """Ri-sostituisce i placeholder canonici con i valori reali (export in chiaro)."""
    if not testo or not mappa:
        return testo
    # Placeholder più lunghi prima, per evitare collisioni di prefisso.
    for ph in sorted(mappa, key=len, reverse=True):
        testo = testo.replace(ph, mappa[ph])
    return testo


def genera_docx(lavoro, in_chiaro: bool = False) -> bytes:
    doc = _documento_base()
    # In chiaro: registro entità a livello di lavoro; altrimenti nessuna sostituzione.
    mappa = lavoro.mappa_entita if in_chiaro else {}

    def chiaro(t):
        return _depseudonimizza(t, mappa)

    doc.add_heading("Bozza di provvedimento", level=0)
    intestazione = doc.add_paragraph()
    intestazione.add_run(lavoro.titolo).bold = True

    avviso = doc.add_paragraph()
    testo_avviso = (
        "Bozza assistita, soggetta a revisione umana. I passaggi contrassegnati "
        "[DA DECIDERE] richiedono la valutazione dell'operatore."
    )
    if in_chiaro:
        testo_avviso += (
            " ATTENZIONE: questo documento contiene i DATI PERSONALI REALI delle parti "
            "(versione in chiaro). Trattare con le dovute cautele."
        )
    nota = avviso.add_run(testo_avviso)
    nota.italic = True

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
            doc.add_paragraph("Non contestazioni:")
            for nc in r.non_contestazioni:
                doc.add_paragraph(chiaro(str(nc)), style="List Bullet")

        allegati = list(r.allegati_collegati.all())
        if allegati:
            p = doc.add_paragraph()
            p.add_run("Allegati collegati: ").bold = True
            p.add_run(", ".join(_nome_file(a.file.name) for a in allegati))

        for q in r.quesiti_aperti:
            p = doc.add_paragraph()
            p.add_run(f"[DA DECIDERE] {chiaro(q)}").italic = True

    # --- P.Q.M. ---
    doc.add_heading("P.Q.M.", level=1)
    if bozza and bozza.pqm:
        doc.add_paragraph(chiaro(bozza.pqm))
    else:
        doc.add_paragraph("[Da compilare dall'operatore]")

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
