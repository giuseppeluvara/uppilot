import base64
import json
import os
import zipfile
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import Documento, Lavoro, SezioneDocumenti
from .states import StatoLavoro


def _estrai_testo_modello(uploaded) -> str:
    """Estrazione inline del testo del modello di redazione (PDF / DOCX / testo)."""
    nome = uploaded.name.lower()
    data = uploaded.read()
    if nome.endswith(".pdf"):
        import fitz

        with fitz.open(stream=data, filetype="pdf") as doc:
            return "\n".join(p.get_text("text") for p in doc).strip()
    if nome.endswith(".docx"):
        from docx import Document as Docx

        return "\n".join(p.text for p in Docx(BytesIO(data)).paragraphs).strip()
    return data.decode("utf-8", errors="ignore").strip()
from .serializers import (
    DocumentoSerializer,
    DocumentoUploadSerializer,
    LavoroSerializer,
)
from .tasks import estrai_testo_documento, pseudonimizza_documento

_MODELLO_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")


def _demo_fonte(doc: Documento, snippet: str, score: float = 0.72) -> dict:
    livello = "alta" if score >= 0.68 else "media" if score >= 0.38 else "bassa"
    label = "Riscontro forte" if livello == "alta" else "Riscontro utile" if livello == "media" else "Riscontro debole"
    return {
        "documento_id": doc.id,
        "documento_nome": os.path.basename(doc.file.name),
        "documento_url": doc.file.url if doc.file else "",
        "sezione": doc.sezione.tipo,
        "sezione_label": doc.sezione.get_tipo_display(),
        "score": score,
        "affidabilita": livello,
        "affidabilita_label": label,
        "termini": [],
        "numeri": [],
        "motivi": ["fascicolo demo"],
        "snippet": snippet,
        "posizione": 0,
        "anchor": f"doc-{doc.id}-snippet-0",
    }


def _crea_demo_documento(lavoro: Lavoro, sezioni: dict[str, SezioneDocumenti], tipo: str, nome: str, testo: str) -> Documento:
    doc = Documento(
        sezione=sezioni[tipo],
        nome_logico=nome.replace("_", " ").replace(".txt", ""),
        ordine=Documento.objects.filter(sezione__lavoro=lavoro).count(),
        tipo_rilevato=nome.replace("_", " ").replace(".txt", ""),
        stato_estrazione=Documento.StatoEstrazione.COMPLETATO,
        metodo_estrazione=Documento.MetodoEstrazione.PDF_NATIVO,
        testo_estratto=testo,
        stato_anonimizzazione=Documento.StatoAnonimizzazione.COMPLETATA,
        pseudonimizzato=True,
        testo_pseudonimizzato=testo,
        mappa_entita={},
        stato_accettazione=Documento.StatoAccettazione.ACCETTATO_SENZA_VERIFICA,
    )
    doc.file.save(f"demo/{lavoro.id}_{nome}", ContentFile(testo.encode("utf-8")), save=False)
    doc.save()
    return doc


def _crea_fascicolo_demo(utente, tipo: str) -> Lavoro:
    from apps.analisi.models import Bozza, FattoProcessuale, Richiesta

    penale = tipo == "penale"
    titolo = (
        "Demo UPP penale appropriazione/truffa"
        if penale
        else "Demo UPP civile appalto e riconvenzionale"
    )
    lavoro = Lavoro.objects.create(
        utente=utente,
        titolo=f"{titolo} - {timezone.now().strftime('%Y-%m-%d %H:%M')}",
        stato=StatoLavoro.BOZZA_GENERATA,
        analisi_stato=Lavoro.StatoAnalisi.COMPLETATA,
        approfondimento_stato=Lavoro.StatoAnalisi.COMPLETATA,
        analisi_progresso={"fase": "demo", "percentuale": 100, "messaggio": "Demo precaricato"},
        approfondimento_progresso={"fase": "demo", "percentuale": 100, "messaggio": "Demo precaricato"},
    )
    sezioni = {
        tipo_sezione: SezioneDocumenti.objects.create(lavoro=lavoro, tipo=tipo_sezione)
        for tipo_sezione in SezioneDocumenti.Tipo.values
    }
    if penale:
        d1 = _crea_demo_documento(lavoro, sezioni, "generici", "01_capo_imputazione.txt", "Capo di imputazione: [PRIVATE_PERSON_1] avrebbe trattenuto euro 24.900 ricevuti come deposito cauzionale.")
        d2 = _crea_demo_documento(lavoro, sezioni, "generici", "02_estratti_bancari.txt", "Estratti: bonifico euro 24.900, successivi pagamenti personali, nessun riversamento al proprietario.")
        d3 = _crea_demo_documento(lavoro, sezioni, "attore", "03_querela.txt", "Querela: la persona offesa chiede responsabilita', restituzione e risarcimento.")
        d4 = _crea_demo_documento(lavoro, sezioni, "convenuto", "04_memoria_difensiva.txt", "Difesa: sostiene acconto/provvigione, assenza di dolo e chiede assoluzione.")
        richieste = [
            (Richiesta.Parte.ATTORE, Richiesta.Tipo.DOMANDA, "Affermare la responsabilita' per appropriazione indebita della somma di euro 24.900.", [d1, d2, d3]),
            (Richiesta.Parte.ATTORE, Richiesta.Tipo.DOMANDA, "In subordine affermare la responsabilita' per truffa.", [d1, d3]),
            (Richiesta.Parte.CONVENUTO, Richiesta.Tipo.DIFESA_ECCEZIONE, "Assolvere per mancanza di dolo e natura civilistica del rapporto.", [d4]),
        ]
    else:
        d1 = _crea_demo_documento(lavoro, sezioni, "generici", "01_contratto_appalto.txt", "Contratto appalto: corrispettivo euro 146.000, termine 30/06/2024, penale euro 500 per giorno.")
        d2 = _crea_demo_documento(lavoro, sezioni, "generici", "02_verbale_collaudo.txt", "Verbale collaudo: temperatura 11-14 gradi, compressore secondario non avviato, collaudo rinviato.")
        d3 = _crea_demo_documento(lavoro, sezioni, "attore", "03_atto_citazione.txt", "Attrice chiede inadempimento, restituzione euro 58.400, risarcimento euro 42.800, penale euro 19.000 e CTU.")
        d4 = _crea_demo_documento(lavoro, sezioni, "convenuto", "04_comparsa.txt", "Convenuta contesta difetti per layout modificato e propone riconvenzionale per euro 87.600 residui.")
        richieste = [
            (Richiesta.Parte.ATTORE, Richiesta.Tipo.DOMANDA, "Accertare il grave inadempimento per ritardo e difetti dell'impianto.", [d1, d2, d3]),
            (Richiesta.Parte.ATTORE, Richiesta.Tipo.DOMANDA, "Applicare la penale contrattuale di euro 19.000.", [d1, d3]),
            (Richiesta.Parte.ATTORE, Richiesta.Tipo.ISTRUTTORIA, "Disporre CTU tecnica sul funzionamento dell'impianto.", [d2, d3, d4]),
            (Richiesta.Parte.CONVENUTO, Richiesta.Tipo.RICONVENZIONALE, "Condannare l'attrice al pagamento di euro 87.600 residui.", [d1, d4]),
        ]
    create_richieste = []
    for ordine, (parte, tipo_richiesta, testo, docs) in enumerate(richieste):
        fonti = [
            _demo_fonte(doc, doc.testo_pseudonimizzato[:260], 0.76 - i * 0.11)
            for i, doc in enumerate(docs)
        ]
        create_richieste.append(
            Richiesta(
                lavoro=lavoro,
                parte_richiedente=parte,
                tipo=tipo_richiesta,
                testo=testo,
                confidence=0.78,
                stato=Richiesta.Stato.APPROFONDITA,
                onere_probatorio="Onere da verificare secondo riparto e fatti costitutivi allegati.",
                motivazione="Bozza demo: verificare prova, contraddittorio e coerenza con gli atti prima della decisione.",
                quesiti_aperti=["Confermare la valutazione del punto controverso e del riparto dell'onere."],
                fonti_tracciate=fonti,
                ordine=ordine,
            )
        )
    Richiesta.objects.bulk_create(create_richieste)
    for richiesta in lavoro.richieste.all():
        FattoProcessuale.objects.create(
            richiesta=richiesta,
            testo=richiesta.testo,
            stato_prova=FattoProcessuale.StatoProva.DA_VERIFICARE,
            stato_contraddittorio=FattoProcessuale.StatoContraddittorio.DA_DECIDERE,
            quesito_umano=(richiesta.quesiti_aperti or [""])[0],
        )
    Bozza.objects.create(
        lavoro=lavoro,
        in_fatto="Fascicolo demo precaricato con documenti sintetici, richieste, fonti e matrice.",
        pqm="P.Q.M. demo: decidere sulle domande previa verifica umana della matrice.",
    )
    return lavoro


def _valida_upload_modello(uploaded):
    if uploaded.size > settings.UPPILOT_MAX_UPLOAD_BYTES:
        return Response(
            {
                "detail": (
                    "File troppo grande. Limite: "
                    f"{settings.UPPILOT_MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not uploaded.name.lower().endswith(_MODELLO_EXTENSIONS):
        return Response(
            {"detail": "Tipo di file non supportato. Usa PDF, DOCX o testo."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None


class LavoroViewSet(viewsets.ModelViewSet):
    """CRUD dei Lavori dell'utente autenticato (storicizzati)."""

    serializer_class = LavoroSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        return (
            Lavoro.objects.filter(utente=self.request.user)
            .prefetch_related("sezioni__documenti")
        )

    @action(detail=False, methods=["post"], url_path="demo")
    def demo(self, request):
        """Crea un fascicolo sintetico gia' analizzato per formazione e test E2E."""
        tipo = (request.data.get("tipo") or "civile").strip().lower()
        if tipo not in {"civile", "penale"}:
            return Response(
                {"detail": "Tipo demo non valido: usa 'civile' o 'penale'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        lavoro = _crea_fascicolo_demo(request.user, tipo)
        return Response(LavoroSerializer(lavoro, context={"request": request}).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="accetta-tutti")
    def accetta_tutti(self, request, pk=None):
        """Accetta in blocco tutti i documenti pseudonimizzati del lavoro (§122)."""
        lavoro = self.get_object()
        documenti = Documento.objects.filter(
            sezione__lavoro=lavoro, pseudonimizzato=True
        )
        aggiornati = documenti.update(
            stato_accettazione=Documento.StatoAccettazione.ACCETTATO_SENZA_VERIFICA
        )
        return Response({"accettati": aggiornati})

    @action(detail=True, methods=["get"], url_path="documenti-zip")
    def documenti_zip(self, request, pk=None):
        """Scarica in un unico .zip tutti i documenti caricati del lavoro."""
        lavoro = self.get_object()
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            usati: set[str] = set()
            for doc in Documento.objects.filter(sezione__lavoro=lavoro).select_related("sezione"):
                if not doc.file:
                    continue
                nome = os.path.basename(doc.file.name)
                # Evita collisioni di nome (cartella per sezione + id se serve).
                arc = f"{doc.sezione.tipo}/{nome}"
                if arc in usati:
                    arc = f"{doc.sezione.tipo}/{doc.id}_{nome}"
                usati.add(arc)
                with doc.file.open("rb") as fh:
                    zf.writestr(arc, fh.read())
        resp = HttpResponse(buffer.getvalue(), content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="documenti_lavoro_{lavoro.id}.zip"'
        return resp

    @action(detail=True, methods=["post"], url_path="modello")
    def modello(self, request, pk=None):
        """Imposta (o cancella) il modello di redazione: file (PDF/DOCX/txt) o testo."""
        lavoro = self.get_object()
        upload = request.FILES.get("file")
        if upload is not None:
            if resp := _valida_upload_modello(upload):
                return resp
            try:
                testo = _estrai_testo_modello(upload)
            except Exception:  # noqa: BLE001
                return Response(
                    {"detail": "Impossibile leggere il file. Usa PDF, DOCX o testo."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            testo = (request.data.get("testo") or "").strip()
        lavoro.modello_testo = testo
        lavoro.save(update_fields=["modello_testo", "updated_at"])
        return Response(LavoroSerializer(lavoro).data)

    @action(detail=True, methods=["post"], url_path="template")
    def template(self, request, pk=None):
        """Applica un profilo di provvedimento al modello di redazione del lavoro."""
        from apps.analisi.views import TEMPLATE_PROVVEDIMENTI

        lavoro = self.get_object()
        template_id = request.data.get("template_id")
        template = next((t for t in TEMPLATE_PROVVEDIMENTI if t["id"] == template_id), None)
        if template is None:
            return Response({"detail": "Template non trovato."}, status=status.HTTP_404_NOT_FOUND)
        lavoro.modello_testo = template["testo"]
        lavoro.save(update_fields=["modello_testo", "updated_at"])
        return Response(LavoroSerializer(lavoro, context={"request": request}).data)

    @action(detail=True, methods=["patch"], url_path="collaborazione")
    def collaborazione(self, request, pk=None):
        """Aggiorna assegnazione, revisore e stato collaborativo del fascicolo."""
        lavoro = self.get_object()
        if request.data.get("assegna_a_me"):
            lavoro.assegnato_a = request.user
        if request.data.get("revisore_a_me"):
            lavoro.revisore = request.user
        stato_revisione = request.data.get("stato_revisione")
        validi = {choice for choice, _ in Lavoro._meta.get_field("stato_revisione").choices}
        if stato_revisione is not None:
            if stato_revisione not in validi:
                return Response({"detail": "Stato revisione non valido."}, status=status.HTTP_400_BAD_REQUEST)
            lavoro.stato_revisione = stato_revisione
        lavoro.save(update_fields=["assegnato_a", "revisore", "stato_revisione", "updated_at"])
        return Response(LavoroSerializer(lavoro, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="estrai-modello")
    def estrai_modello(self, request, pk=None):
        """Estrae il testo da un file SENZA salvarlo: l'operatore lo rivede e poi salva."""
        self.get_object()  # verifica proprietà del lavoro
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Nessun file."}, status=status.HTTP_400_BAD_REQUEST)
        if resp := _valida_upload_modello(upload):
            return resp
        try:
            testo = _estrai_testo_modello(upload)
        except Exception:  # noqa: BLE001
            return Response(
                {"detail": "Impossibile leggere il file. Usa PDF, DOCX o testo."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"testo": testo})

    @action(detail=True, methods=["get"], url_path="backup")
    def backup(self, request, pk=None):
        """Esporta un lavoro completo in JSON portabile."""
        from apps.analisi.models import Bozza, CommentoEditor, FattoProcessuale, Richiesta

        lavoro = self.get_object()
        documenti_payload = []
        for doc in Documento.objects.filter(sezione__lavoro=lavoro).select_related("sezione"):
            file_b64 = ""
            file_name = os.path.basename(doc.file.name) if doc.file else ""
            if doc.file:
                try:
                    with doc.file.open("rb") as fh:
                        file_b64 = base64.b64encode(fh.read()).decode("ascii")
                except OSError:
                    file_b64 = ""
            documenti_payload.append(
                {
                    "id": doc.id,
                    "sezione": doc.sezione.tipo,
                    "file_name": file_name,
                    "file_base64": file_b64,
                    "nome_logico": doc.nome_logico,
                    "ordine": doc.ordine,
                    "tipo_rilevato": doc.tipo_rilevato,
                    "testo_estratto": doc.testo_estratto,
                    "testo_pseudonimizzato": doc.testo_pseudonimizzato,
                    "mappa_entita": doc.mappa_entita,
                    "pseudonimizzato": doc.pseudonimizzato,
                    "stato_accettazione": doc.stato_accettazione,
                    "metodo_estrazione": doc.metodo_estrazione,
                    "flag_bassa_confidenza": doc.flag_bassa_confidenza,
                    "passaggi_incerti": doc.passaggi_incerti,
                }
            )
        payload = {
            "versione": 1,
            "lavoro": {
                "titolo": lavoro.titolo,
                "stato": lavoro.stato,
                "analisi_stato": lavoro.analisi_stato,
                "approfondimento_stato": lavoro.approfondimento_stato,
                "ricerca_stato": lavoro.ricerca_stato,
                "mappa_entita": lavoro.mappa_entita,
                "modello_testo": lavoro.modello_testo,
            },
            "documenti": documenti_payload,
            "richieste": [
                {
                    "id": r.id,
                    "parte_richiedente": r.parte_richiedente,
                    "tipo": r.tipo,
                    "testo": r.testo,
                    "confidence": r.confidence,
                    "flags": r.flags,
                    "stato": r.stato,
                    "onere_probatorio": r.onere_probatorio,
                    "non_contestazioni": r.non_contestazioni,
                    "quesiti_aperti": r.quesiti_aperti,
                    "motivazione": r.motivazione,
                    "fonti_tracciate": r.fonti_tracciate,
                    "ordine": r.ordine,
                    "allegati_collegati": list(r.allegati_collegati.values_list("id", flat=True)),
                }
                for r in Richiesta.objects.filter(lavoro=lavoro).order_by("ordine", "id")
            ],
            "matrice": [
                {
                    "richiesta_id": f.richiesta_id,
                    "testo": f.testo,
                    "stato_prova": f.stato_prova,
                    "funzione_prevalente": f.funzione_prevalente,
                    "stato_contraddittorio": f.stato_contraddittorio,
                    "note_operatore": f.note_operatore,
                    "note_contraddittorio": f.note_contraddittorio,
                    "quesito_umano": f.quesito_umano,
                    "ordine": f.ordine,
                }
                for f in FattoProcessuale.objects.filter(richiesta__lavoro=lavoro)
            ],
            "bozza": (
                {
                    "in_fatto": lavoro.bozza.in_fatto,
                    "pqm": lavoro.bozza.pqm,
                    "contenuto_per_richiesta": lavoro.bozza.contenuto_per_richiesta,
                    "versione": lavoro.bozza.versione,
                }
                if Bozza.objects.filter(lavoro=lavoro).exists()
                else None
            ),
            "commenti": [
                {
                    "sezione": c.sezione,
                    "riferimento_id": c.riferimento_id,
                    "testo": c.testo,
                    "risolto": c.risolto,
                }
                for c in CommentoEditor.objects.filter(lavoro=lavoro)
            ],
        }
        contenuto = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        resp = HttpResponse(contenuto, content_type="application/json")
        resp["Content-Disposition"] = f'attachment; filename="uppilot_backup_{lavoro.id}.json"'
        return resp

    @action(detail=False, methods=["post"], url_path="importa-backup")
    def importa_backup(self, request):
        """Importa un backup JSON esportato da UPPilot."""
        from apps.analisi.models import Bozza, CommentoEditor, FattoProcessuale, Richiesta

        payload = request.data
        if not isinstance(payload, dict) or "lavoro" not in payload:
            return Response({"detail": "Backup non valido."}, status=status.HTTP_400_BAD_REQUEST)
        lavoro_data = payload["lavoro"]
        lavoro = Lavoro.objects.create(
            utente=request.user,
            titolo=request.data.get("titolo") or f"Import - {lavoro_data.get('titolo', 'lavoro')}",
            stato=lavoro_data.get("stato") or StatoLavoro.BOZZA_GENERATA,
            analisi_stato=lavoro_data.get("analisi_stato") or Lavoro.StatoAnalisi.COMPLETATA,
            approfondimento_stato=lavoro_data.get("approfondimento_stato") or Lavoro.StatoAnalisi.IN_ATTESA,
            ricerca_stato=lavoro_data.get("ricerca_stato") or Lavoro.StatoAnalisi.IN_ATTESA,
            mappa_entita=lavoro_data.get("mappa_entita") or {},
            modello_testo=lavoro_data.get("modello_testo") or "",
        )
        sezioni = {
            tipo: SezioneDocumenti.objects.create(lavoro=lavoro, tipo=tipo)
            for tipo in SezioneDocumenti.Tipo.values
        }
        doc_map: dict[int, int] = {}
        for d in payload.get("documenti", []):
            doc = Documento(
                sezione=sezioni.get(d.get("sezione")) or sezioni[SezioneDocumenti.Tipo.GENERICI],
                nome_logico=d.get("nome_logico", ""),
                ordine=d.get("ordine") or 0,
                tipo_rilevato=d.get("tipo_rilevato", ""),
                stato_estrazione=Documento.StatoEstrazione.COMPLETATO,
                metodo_estrazione=d.get("metodo_estrazione") or Documento.MetodoEstrazione.PDF_NATIVO,
                testo_estratto=d.get("testo_estratto", ""),
                stato_anonimizzazione=Documento.StatoAnonimizzazione.COMPLETATA,
                pseudonimizzato=bool(d.get("pseudonimizzato", True)),
                testo_pseudonimizzato=d.get("testo_pseudonimizzato", ""),
                mappa_entita=d.get("mappa_entita") or {},
                stato_accettazione=d.get("stato_accettazione") or Documento.StatoAccettazione.ACCETTATO_SENZA_VERIFICA,
                flag_bassa_confidenza=bool(d.get("flag_bassa_confidenza", False)),
                passaggi_incerti=d.get("passaggi_incerti") or [],
            )
            raw = base64.b64decode(d.get("file_base64") or b"") if d.get("file_base64") else (doc.testo_estratto or "").encode("utf-8")
            nome = d.get("file_name") or f"documento_{d.get('id', 'import')}.txt"
            doc.file.save(f"import/{lavoro.id}_{nome}", ContentFile(raw), save=False)
            doc.save()
            if d.get("id") is not None:
                doc_map[int(d["id"])] = doc.id

        richiesta_map: dict[int, int] = {}
        for r in payload.get("richieste", []):
            fonti = []
            for fonte in r.get("fonti_tracciate") or []:
                if isinstance(fonte, dict):
                    fonte = dict(fonte)
                    old_doc = fonte.get("documento_id")
                    if old_doc in doc_map:
                        fonte["documento_id"] = doc_map[old_doc]
                    fonti.append(fonte)
            richiesta = Richiesta.objects.create(
                lavoro=lavoro,
                parte_richiedente=r.get("parte_richiedente") or Richiesta.Parte.ATTORE,
                tipo=r.get("tipo") or Richiesta.Tipo.DOMANDA,
                testo=r.get("testo", ""),
                confidence=r.get("confidence") or 0.65,
                flags=r.get("flags") or [],
                stato=r.get("stato") or Richiesta.Stato.APPROFONDITA,
                onere_probatorio=r.get("onere_probatorio", ""),
                non_contestazioni=r.get("non_contestazioni") or [],
                quesiti_aperti=r.get("quesiti_aperti") or [],
                motivazione=r.get("motivazione", ""),
                fonti_tracciate=fonti,
                ordine=r.get("ordine") or 0,
            )
            richiesta.allegati_collegati.set(
                doc_map[x] for x in r.get("allegati_collegati", []) if x in doc_map
            )
            if r.get("id") is not None:
                richiesta_map[int(r["id"])] = richiesta.id

        for f in payload.get("matrice", []):
            richiesta_id = richiesta_map.get(int(f.get("richiesta_id") or 0))
            if not richiesta_id:
                continue
            FattoProcessuale.objects.create(
                richiesta_id=richiesta_id,
                testo=f.get("testo", ""),
                stato_prova=f.get("stato_prova") or FattoProcessuale.StatoProva.DA_VERIFICARE,
                funzione_prevalente=f.get("funzione_prevalente") or FattoProcessuale.FunzioneFonte.SUPPORTA,
                stato_contraddittorio=f.get("stato_contraddittorio") or FattoProcessuale.StatoContraddittorio.DA_DECIDERE,
                note_operatore=f.get("note_operatore", ""),
                note_contraddittorio=f.get("note_contraddittorio", ""),
                quesito_umano=f.get("quesito_umano", ""),
                ordine=f.get("ordine") or 0,
            )
        if payload.get("bozza"):
            Bozza.objects.create(
                lavoro=lavoro,
                in_fatto=payload["bozza"].get("in_fatto", ""),
                pqm=payload["bozza"].get("pqm", ""),
                contenuto_per_richiesta=payload["bozza"].get("contenuto_per_richiesta") or {},
                versione=payload["bozza"].get("versione") or 1,
            )
        for c in payload.get("commenti", []):
            CommentoEditor.objects.create(
                lavoro=lavoro,
                utente=request.user,
                sezione=c.get("sezione") or CommentoEditor.Sezione.GENERALE,
                riferimento_id=c.get("riferimento_id"),
                testo=c.get("testo", ""),
                risolto=bool(c.get("risolto", False)),
            )
        return Response(LavoroSerializer(lavoro, context={"request": request}).data, status=status.HTTP_201_CREATED)


class DocumentoViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Upload e consultazione dei documenti dell'utente."""

    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_serializer_class(self):
        if self.action == "create":
            return DocumentoUploadSerializer
        return DocumentoSerializer

    def get_queryset(self):
        return Documento.objects.filter(
            sezione__lavoro__utente=self.request.user
        )

    def perform_create(self, serializer):
        documento = serializer.save()
        # Estrazione testo asincrona (§82): non blocca la risposta.
        estrai_testo_documento.delay(documento.id)

    def _imposta_accettazione(self, documento, nuovo_stato):
        # Vincolo §119: si può accettare solo dopo la pseudonimizzazione.
        if not documento.pseudonimizzato:
            return Response(
                {"detail": "Documento non ancora pseudonimizzato."},
                status=status.HTTP_409_CONFLICT,
            )
        documento.stato_accettazione = nuovo_stato
        documento.save(update_fields=["stato_accettazione"])
        return Response(DocumentoSerializer(documento).data)

    @action(detail=True, methods=["patch"], url_path="privacy")
    def privacy(self, request, pk=None):
        """Correzione manuale del testo pseudonimizzato e della mappa entità."""
        documento = self.get_object()
        testo = request.data.get("testo_pseudonimizzato")
        mappa = request.data.get("mappa_entita")
        campi: list[str] = []

        if testo is not None:
            documento.testo_pseudonimizzato = str(testo)
            documento.pseudonimizzato = bool(str(testo).strip())
            campi.extend(["testo_pseudonimizzato", "pseudonimizzato"])
        if mappa is not None:
            if not isinstance(mappa, dict):
                return Response(
                    {"detail": "mappa_entita deve essere un oggetto chiave/valore."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            documento.mappa_entita = {str(k): str(v) for k, v in mappa.items()}
            campi.append("mappa_entita")

        if campi:
            # Ogni modifica manuale richiede nuova conferma: evita che un documento
            # già accettato resti utilizzabile dopo una correzione non revisionata.
            documento.stato_accettazione = Documento.StatoAccettazione.DA_VERIFICARE
            if "stato_accettazione" not in campi:
                campi.append("stato_accettazione")
            documento.save(update_fields=campi)

            lavoro = documento.sezione.lavoro
            registro = dict(lavoro.mappa_entita or {})
            registro.update(documento.mappa_entita or {})
            lavoro.mappa_entita = registro
            lavoro.save(update_fields=["mappa_entita", "updated_at"])

        return Response(DocumentoSerializer(documento).data)

    @action(detail=True, methods=["patch"], url_path="metadata")
    def metadata(self, request, pk=None):
        """Rinomina logica, ordinamento e classificazione visibile del documento."""
        documento = self.get_object()
        campi = []
        if "nome_logico" in request.data:
            documento.nome_logico = str(request.data.get("nome_logico") or "")[:255]
            campi.append("nome_logico")
        if "ordine" in request.data:
            try:
                documento.ordine = max(0, int(request.data.get("ordine") or 0))
            except (TypeError, ValueError):
                return Response({"detail": "Ordine non valido."}, status=status.HTTP_400_BAD_REQUEST)
            campi.append("ordine")
        if "tipo_rilevato" in request.data:
            documento.tipo_rilevato = str(request.data.get("tipo_rilevato") or "")[:64]
            campi.append("tipo_rilevato")
        if campi:
            documento.save(update_fields=campi)
        return Response(DocumentoSerializer(documento).data)

    @action(detail=True, methods=["post"])
    def verifica(self, request, pk=None):
        """L'utente ha rivisto l'anonimizzazione e la conferma (§122)."""
        return self._imposta_accettazione(
            self.get_object(), Documento.StatoAccettazione.VERIFICATO
        )

    @action(detail=True, methods=["post"])
    def accetta(self, request, pk=None):
        """L'utente accetta senza verifica il singolo documento (§122)."""
        return self._imposta_accettazione(
            self.get_object(), Documento.StatoAccettazione.ACCETTATO_SENZA_VERIFICA
        )

    @action(detail=True, methods=["post"])
    def ripseudonimizza(self, request, pk=None):
        """Riprova l'anonimizzazione di un documento (resilienza)."""
        documento = self.get_object()
        pseudonimizza_documento.delay(documento.id)
        documento.stato_anonimizzazione = Documento.StatoAnonimizzazione.IN_CORSO
        documento.errore_anonimizzazione = ""
        documento.save(update_fields=["stato_anonimizzazione", "errore_anonimizzazione"])
        return Response(DocumentoSerializer(documento).data, status=status.HTTP_202_ACCEPTED)
