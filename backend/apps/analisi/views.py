from celery import current_app
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from ai.factory import commerciale_disponibile
from apps.casi.models import Documento, Lavoro
from apps.casi.privacy import maschera_residui, privacy_report

from .export import genera_audit_docx, genera_docx
from .models import (
    Bozza,
    CommentoEditor,
    EventoDecisionale,
    FattoProcessuale,
    Richiesta,
    SpuntoRicerca,
)
from .serializers import (
    BozzaSerializer,
    CommentoEditorSerializer,
    EventoDecisionaleSerializer,
    FattoProcessualeSerializer,
    RichiestaSerializer,
    SpuntoRicercaSerializer,
)
from .services import documenti_utilizzabili
from .tasks import (
    analizza_lavoro_task,
    approfondisci_lavoro_task,
    approfondisci_richiesta_task,
    ricerca_manuale_task,
    ricerca_spunti_task,
)

DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _lavoro_utente(request, lavoro_id) -> Lavoro:
    return get_object_or_404(Lavoro, pk=lavoro_id, utente=request.user)


def _fase_gia_in_corso(lavoro: Lavoro, campo_stato: str, nome: str):
    if getattr(lavoro, campo_stato) != Lavoro.StatoAnalisi.IN_CORSO:
        return None
    return Response(
        {"detail": f"{nome} già in corso. Interrompila o attendi il completamento."},
        status=status.HTTP_409_CONFLICT,
    )


def _marca_in_corso(
    lavoro: Lavoro,
    campo_stato: str,
    campo_errore: str,
    campo_progresso: str | None = None,
    messaggio: str = "Elaborazione avviata",
) -> None:
    setattr(lavoro, campo_stato, Lavoro.StatoAnalisi.IN_CORSO)
    setattr(lavoro, campo_errore, "")
    campi = [campo_stato, campo_errore]
    if campo_progresso:
        setattr(
            lavoro,
            campo_progresso,
            {
                "fase": "avvio",
                "corrente": 0,
                "totale": 1,
                "percentuale": 0,
                "messaggio": messaggio,
            },
        )
        campi.append(campo_progresso)
    lavoro.save(update_fields=campi)


def _salva_task_id_se_ancora_in_corso(
    lavoro: Lavoro, campo_stato: str, campo_task: str, task_id: str
) -> None:
    lavoro.refresh_from_db(fields=[campo_stato])
    setattr(
        lavoro,
        campo_task,
        task_id if getattr(lavoro, campo_stato) == Lavoro.StatoAnalisi.IN_CORSO else "",
    )
    lavoro.save(update_fields=[campo_task])


# Warning inequivocabile per l'uso di LLM commerciale in cloud (§5/§125).
WARNING_COMMERCIALE = (
    "Stai inviando testo PSEUDONIMIZZATO (non anonimizzato) a un LLM commerciale "
    "in cloud: ai fini del GDPR resta dato personale. Procedi solo se consapevole."
)


def _opt_in_commerciale(request):
    """Legge il flag opt-in LLM commerciale e lo valida (§5).

    Ritorna (commerciale: bool, warning: str|None). Solleva ValueError se
    richiesto ma non configurato (gestito dal chiamante come 400).
    """
    commerciale = bool(request.data.get("commerciale"))
    if commerciale and not commerciale_disponibile():
        raise ValueError("LLM commerciale non configurato (manca la chiave API).")
    return commerciale, (WARNING_COMMERCIALE if commerciale else None)


def _documenti_da_verificare(lavoro: Lavoro):
    return Documento.objects.filter(
        sezione__lavoro=lavoro,
        pseudonimizzato=True,
        stato_accettazione=Documento.StatoAccettazione.DA_VERIFICARE,
    )


def _testo_fatto_iniziale(richiesta: Richiesta) -> str:
    testo = (richiesta.testo or "").strip()
    if len(testo) <= 320:
        return testo
    return testo[:317].rstrip() + "..."


def _quesito_matrice_iniziale(richiesta: Richiesta) -> str:
    quesiti = [str(q).strip() for q in (richiesta.quesiti_aperti or []) if str(q).strip()]
    if quesiti:
        return quesiti[0]
    if not (richiesta.onere_probatorio or "").strip():
        return "Quali fatti costitutivi/impeditivi e quali prove sorreggono questa richiesta?"
    return ""


def _sincronizza_matrice_lavoro(lavoro: Lavoro) -> None:
    """Crea una prima riga matrice per ogni richiesta priva di fatti.

    La matrice parte minimale: una riga per richiesta. In seguito la riga potrà
    essere spezzata manualmente in più fatti processuali senza perdere il legame
    con la richiesta.
    """

    richieste = list(Richiesta.objects.filter(lavoro=lavoro).order_by("ordine", "id"))
    esistenti = set(
        FattoProcessuale.objects.filter(richiesta__lavoro=lavoro).values_list(
            "richiesta_id", flat=True
        )
    )
    FattoProcessuale.objects.bulk_create(
        FattoProcessuale(
            richiesta=richiesta,
            testo=_testo_fatto_iniziale(richiesta),
            quesito_umano=_quesito_matrice_iniziale(richiesta),
            ordine=0,
        )
        for richiesta in richieste
        if richiesta.id not in esistenti
    )


def _registra_evento(
    *,
    lavoro: Lavoro,
    utente,
    tipo: str,
    descrizione: str = "",
    richiesta: Richiesta | None = None,
    fatto: FattoProcessuale | None = None,
    campo: str = "",
    valore_precedente=None,
    valore_nuovo=None,
) -> None:
    EventoDecisionale.objects.create(
        lavoro=lavoro,
        utente=utente if getattr(utente, "is_authenticated", False) else None,
        richiesta=richiesta,
        fatto=fatto,
        tipo=tipo,
        campo=campo,
        descrizione=descrizione,
        valore_precedente=valore_precedente or {},
        valore_nuovo=valore_nuovo or {},
    )


def _red_team_lavoro(lavoro: Lavoro) -> dict:
    _sincronizza_matrice_lavoro(lavoro)
    issues = []
    righe = (
        FattoProcessuale.objects.filter(richiesta__lavoro=lavoro)
        .select_related("richiesta", "richiesta__lavoro")
        .prefetch_related("richiesta__allegati_collegati")
    )
    for fatto in righe:
        data = FattoProcessualeSerializer(fatto).data
        richiesta = fatto.richiesta
        base = {
            "richiesta_id": richiesta.id,
            "fatto_id": fatto.id,
            "richiesta": richiesta.testo,
        }
        if data["fonti_count"] == 0:
            issues.append(
                {
                    **base,
                    "severita": "alta",
                    "ambito": "prove",
                    "messaggio": "Richiesta senza fonti interne agganciate.",
                    "azione_suggerita": "Collega documenti o marca il fatto come non provato/insufficiente.",
                }
            )
        elif data["score_massimo"] < 0.45:
            issues.append(
                {
                    **base,
                    "severita": "media",
                    "ambito": "prove",
                    "messaggio": "Fonti presenti ma con score debole.",
                    "azione_suggerita": "Verifica manualmente snippet e pertinenza della fonte.",
                }
            )
        if data["stato_suggerito"] == FattoProcessuale.StatoProva.INSUFFICIENTE and fatto.stato_prova == FattoProcessuale.StatoProva.PROVATO:
            issues.append(
                {
                    **base,
                    "severita": "alta",
                    "ambito": "stato prova",
                    "messaggio": "La riga è marcata provata, ma il sistema suggerisce insufficienza.",
                    "azione_suggerita": "Motiva nelle note perché il fatto è provato o cambia stato prova.",
                }
            )
        if richiesta.quesiti_aperti and fatto.stato_prova == FattoProcessuale.StatoProva.PROVATO:
            issues.append(
                {
                    **base,
                    "severita": "media",
                    "ambito": "decisione umana",
                    "messaggio": "Fatto marcato provato nonostante quesiti aperti.",
                    "azione_suggerita": "Risolvi i quesiti o sposta lo stato su da decidere/controverso.",
                }
            )
        if fatto.stato_contraddittorio == FattoProcessuale.StatoContraddittorio.SILENTE and not fatto.note_contraddittorio:
            issues.append(
                {
                    **base,
                    "severita": "bassa",
                    "ambito": "contraddittorio",
                    "messaggio": "Controparte silente senza nota esplicativa.",
                    "azione_suggerita": "Annota se il silenzio equivale a non contestazione o richiede verifica.",
                }
            )
        if data["fonti_controparte"] and fatto.stato_contraddittorio in {
            FattoProcessuale.StatoContraddittorio.NON_CONTESTATO,
            FattoProcessuale.StatoContraddittorio.PACIFICO,
        }:
            issues.append(
                {
                    **base,
                    "severita": "alta",
                    "ambito": "contraddittorio",
                    "messaggio": "Sono presenti fonti della controparte ma il contraddittorio è marcato pacifico/non contestato.",
                    "azione_suggerita": "Rivedi lo stato del contraddittorio o motiva la non contestazione.",
                }
            )
        if not (richiesta.motivazione or "").strip():
            issues.append(
                {
                    **base,
                    "severita": "media",
                    "ambito": "motivazione",
                    "messaggio": "Motivazione in diritto non compilata.",
                    "azione_suggerita": "Completa la motivazione o lascia un quesito umano esplicito.",
                }
            )
        if richiesta.motivazione and fatto.stato_prova in {
            FattoProcessuale.StatoProva.NON_PROVATO,
            FattoProcessuale.StatoProva.INSUFFICIENTE,
        }:
            issues.append(
                {
                    **base,
                    "severita": "alta",
                    "ambito": "motivazione/prova",
                    "messaggio": "Motivazione presente su una riga marcata non provata o insufficiente.",
                    "azione_suggerita": "Allinea motivazione e stato prova prima dell'export.",
                }
            )

    bozza = Bozza.objects.filter(lavoro=lavoro).first()
    if not bozza or not (bozza.pqm or "").strip():
        issues.append(
            {
                "richiesta_id": None,
                "fatto_id": None,
                "richiesta": "",
                "severita": "alta",
                "ambito": "PQM",
                "messaggio": "P.Q.M. non compilato.",
                "azione_suggerita": "Compila il dispositivo prima della revisione finale.",
            }
        )
    elif any(not (r.motivazione or "").strip() for r in lavoro.richieste.all()):
        issues.append(
            {
                "richiesta_id": None,
                "fatto_id": None,
                "richiesta": "",
                "severita": "alta",
                "ambito": "PQM/motivazione",
                "messaggio": "P.Q.M. compilato con una o più motivazioni mancanti.",
                "azione_suggerita": "Completa le motivazioni prima di consolidare il dispositivo.",
            }
        )

    conteggi = {
        "alta": sum(1 for i in issues if i["severita"] == "alta"),
        "media": sum(1 for i in issues if i["severita"] == "media"),
        "bassa": sum(1 for i in issues if i["severita"] == "bassa"),
    }
    return {"ok": not issues, "totale": len(issues), "conteggi": conteggi, "issues": issues}


TEMPLATE_PROVVEDIMENTI = [
    {
        "id": "civile_ordinario",
        "label": "Civile ordinario",
        "ambito": "civile",
        "testo": (
            "Struttura: Svolgimento del processo; Motivi della decisione; P.Q.M. "
            "Metodo: separa domande, eccezioni e istruttoria; esplicita onere probatorio "
            "e fatti controversi; mantieni le valutazioni discrezionali come quesiti."
        ),
    },
    {
        "id": "appalto",
        "label": "Appalto",
        "ambito": "civile",
        "testo": (
            "Struttura: rapporto contrattuale; consegna/collaudo; contestazioni tecniche; "
            "penali; danni; riconvenzionale. Metodo: distinguere difetti, ritardo, nesso "
            "causale, concause e utilita' di CTU."
        ),
    },
    {
        "id": "opposizione_di",
        "label": "Opposizione a decreto ingiuntivo",
        "ambito": "civile",
        "testo": (
            "Struttura: decreto opposto; motivi di opposizione; prova del credito; eccezioni; "
            "decisione su revoca/conferma. Metodo: verifica titolo, esigibilita', contestazioni "
            "specifiche e riparto dell'onere."
        ),
    },
    {
        "id": "responsabilita",
        "label": "Responsabilita' civile",
        "ambito": "civile",
        "testo": (
            "Struttura: fatto dannoso; condotta; nesso causale; danno; concorso; liquidazione. "
            "Metodo: separa allegazione, prova, causalita' e quantificazione."
        ),
    },
    {
        "id": "penale",
        "label": "Penale",
        "ambito": "penale",
        "testo": (
            "Struttura: imputazione; prove dell'accusa; difese; qualificazione giuridica; "
            "trattamento sanzionatorio o formule assolutorie; statuizioni civili. Metodo: "
            "tenere distinto fatto storico, elemento soggettivo e alternative ricostruttive."
        ),
    },
    {
        "id": "cautelare",
        "label": "Cautelare",
        "ambito": "civile",
        "testo": (
            "Struttura: fumus; periculum; bilanciamento; misura. Metodo: evidenzia urgenza, "
            "irreparabilita', proporzionalita' e punti da decidere."
        ),
    },
    {
        "id": "lavoro",
        "label": "Lavoro",
        "ambito": "lavoro",
        "testo": (
            "Struttura: rapporto; mansioni/inquadramento; fatti contestati; prova; conteggi; "
            "decisione. Metodo: distinguere allegazioni datoriali e del lavoratore, documenti "
            "retributivi e prova testimoniale."
        ),
    },
]


def _testi_privacy_lavoro(lavoro: Lavoro) -> list[str]:
    testi = [
        d.testo_pseudonimizzato
        for d in Documento.objects.filter(sezione__lavoro=lavoro)
    ]
    bozza = Bozza.objects.filter(lavoro=lavoro).first()
    if bozza:
        testi.extend([bozza.in_fatto, bozza.pqm])
    for r in lavoro.richieste.all():
        testi.extend(
            [
                r.testo,
                r.onere_probatorio,
                r.motivazione,
                "\n".join(
                    str(f.get("snippet", ""))
                    for f in (r.fonti_tracciate or [])
                    if isinstance(f, dict)
                ),
                "\n".join(r.non_contestazioni or []),
                "\n".join(r.quesiti_aperti or []),
            ]
        )
    mappa = lavoro.mappa_entita or {}
    return [maschera_residui(testo, mappa) for testo in testi]


def _progress_snapshot(lavoro: Lavoro) -> dict:
    return {
        "analisi": lavoro.analisi_progresso or {},
        "approfondimento": lavoro.approfondimento_progresso or {},
        "ricerca": lavoro.ricerca_progresso or {},
        "stati": {
            "analisi": lavoro.analisi_stato,
            "approfondimento": lavoro.approfondimento_stato,
            "ricerca": lavoro.ricerca_stato,
        },
    }


def _azione(
    tipo: str,
    label: str,
    descrizione: str,
    *,
    fatto_id=None,
    richiesta_id=None,
    severita="media",
) -> dict:
    return {
        "tipo": tipo,
        "label": label,
        "descrizione": descrizione,
        "fatto_id": fatto_id,
        "richiesta_id": richiesta_id,
        "severita": severita,
    }


def _azioni_da_issue(issue: dict) -> list[dict]:
    fatto_id = issue.get("fatto_id")
    richiesta_id = issue.get("richiesta_id")
    ambito = (issue.get("ambito") or "").casefold()
    messaggio = (issue.get("messaggio") or "").casefold()
    azioni: list[dict] = []
    if "prove" in ambito and "senza fonti" in messaggio:
        azioni.extend(
            [
                _azione(
                    "cerca_fascicolo",
                    "Cercare nel fascicolo",
                    "Apri la richiesta e verifica se uno snippet pertinente non e' stato agganciato.",
                    fatto_id=fatto_id,
                    richiesta_id=richiesta_id,
                    severita=issue.get("severita", "alta"),
                ),
                _azione(
                    "segna_insufficiente",
                    "Segna prova insufficiente",
                    "Marca la riga come insufficiente finche' non viene collegata una fonte.",
                    fatto_id=fatto_id,
                    richiesta_id=richiesta_id,
                    severita=issue.get("severita", "alta"),
                ),
                _azione(
                    "crea_quesito",
                    "Crea quesito umano",
                    "Aggiunge un quesito operativo sulla mancanza di prova interna.",
                    fatto_id=fatto_id,
                    richiesta_id=richiesta_id,
                    severita=issue.get("severita", "alta"),
                ),
            ]
        )
    elif "prove" in ambito and "score debole" in messaggio:
        azioni.extend(
            [
                _azione(
                    "verifica_fonti",
                    "Verifica snippet",
                    "Controlla manualmente gli snippet e marca le fonti decisive o irrilevanti.",
                    fatto_id=fatto_id,
                    richiesta_id=richiesta_id,
                    severita=issue.get("severita", "media"),
                ),
                _azione(
                    "segna_da_verificare",
                    "Mantieni da verificare",
                    "Lascia la riga in verifica fino a conferma della pertinenza.",
                    fatto_id=fatto_id,
                    richiesta_id=richiesta_id,
                    severita=issue.get("severita", "media"),
                ),
            ]
        )
    if "motivazione" in ambito:
        azioni.append(
            _azione(
                "integra_motivazione",
                "Integra motivazione",
                "Apre una nota editoriale per completare o riallineare la motivazione.",
                fatto_id=fatto_id,
                richiesta_id=richiesta_id,
                severita=issue.get("severita", "media"),
            )
        )
    if "pqm" in ambito:
        azioni.append(
            _azione(
                "compila_pqm",
                "Compila P.Q.M.",
                "Crea una nota editoriale sul dispositivo mancante o incoerente.",
                severita=issue.get("severita", "alta"),
            )
        )
    if not azioni and fatto_id:
        azioni.append(
            _azione(
                "crea_quesito",
                "Crea quesito umano",
                issue.get("azione_suggerita") or "Aggiungi un punto di verifica.",
                fatto_id=fatto_id,
                richiesta_id=richiesta_id,
                severita=issue.get("severita", "media"),
            )
        )
    return azioni


def _report_revisione_lavoro(lavoro: Lavoro) -> dict:
    _sincronizza_matrice_lavoro(lavoro)
    documenti = list(Documento.objects.filter(sezione__lavoro=lavoro).select_related("sezione"))
    richieste = list(lavoro.richieste.all().order_by("ordine", "id"))
    righe = list(
        FattoProcessuale.objects.filter(richiesta__lavoro=lavoro)
        .select_related("richiesta")
        .order_by("richiesta__ordine", "ordine", "id")
    )
    righe_data = [FattoProcessualeSerializer(r).data for r in righe]
    bozza = Bozza.objects.filter(lavoro=lavoro).first()
    privacy = privacy_report(
        _testi_privacy_lavoro(lavoro), lavoro.mappa_entita or {}, extra_values=[lavoro.titolo]
    )
    red = _red_team_lavoro(lavoro)

    doc_pronti = [d for d in documenti if d.utilizzabile]
    doc_da_verificare = [
        d
        for d in documenti
        if d.pseudonimizzato and d.stato_accettazione == Documento.StatoAccettazione.DA_VERIFICARE
    ]
    doc_in_lavorazione = [
        d
        for d in documenti
        if d.stato_estrazione in {Documento.StatoEstrazione.IN_ATTESA, Documento.StatoEstrazione.IN_CORSO}
        or d.stato_anonimizzazione == Documento.StatoAnonimizzazione.IN_CORSO
    ]
    nomi = {}
    duplicati = []
    for d in documenti:
        nome = (d.file.name or "").rsplit("/", 1)[-1].casefold()
        if nome in nomi:
            duplicati.append({"documento_id": d.id, "nome": nome, "simile_a": nomi[nome]})
        else:
            nomi[nome] = d.id

    fonti = [
        f
        for r in richieste
        for f in (r.fonti_tracciate or [])
        if isinstance(f, dict)
    ]
    fonti_usate = {int(f.get("documento_id")) for f in fonti if f.get("documento_id")}
    fonti_deboli = [f for f in fonti if float(f.get("score") or 0) < 0.45]
    fonti_decisive = [f for f in fonti if f.get("valutazione_operatore") == "decisiva"]
    righe_senza_fonti = [r for r in righe_data if r["fonti_count"] == 0]
    richieste_bassa_conf = [r for r in richieste if (r.confidence or 0) < 0.55]
    quesiti_aperti = sum(len(r.quesiti_aperti or []) for r in richieste)
    motivazioni_mancanti = [r.id for r in richieste if not (r.motivazione or "").strip()]
    contraddizioni = [
        r
        for r in righe
        if r.richiesta.motivazione
        and r.stato_prova
        in {FattoProcessuale.StatoProva.NON_PROVATO, FattoProcessuale.StatoProva.INSUFFICIENTE}
    ]

    blocchi = []
    avvisi = []
    if not documenti:
        blocchi.append("Nessun documento caricato.")
    if doc_in_lavorazione:
        blocchi.append(f"{len(doc_in_lavorazione)} documenti ancora in lavorazione.")
    if doc_da_verificare:
        blocchi.append(f"{len(doc_da_verificare)} documenti pseudonimizzati da verificare.")
    if not doc_pronti:
        blocchi.append("Nessun documento accettato e utilizzabile.")
    if lavoro.analisi_stato != Lavoro.StatoAnalisi.COMPLETATA:
        blocchi.append("Analisi richieste non completata.")
    if not richieste and lavoro.analisi_stato == Lavoro.StatoAnalisi.COMPLETATA:
        blocchi.append("Analisi completata ma nessuna richiesta estratta.")
    if not bozza:
        blocchi.append("Bozza non generata.")
    elif not (bozza.pqm or "").strip():
        blocchi.append("P.Q.M. non compilato.")
    if motivazioni_mancanti:
        blocchi.append(f"{len(motivazioni_mancanti)} motivazioni in diritto mancanti.")
    if not privacy["ok"]:
        blocchi.append("Controllo privacy non pulito.")
    if red["conteggi"]["alta"]:
        blocchi.append(f"{red['conteggi']['alta']} criticita' alte nel red-team.")
    if fonti_deboli:
        avvisi.append(f"{len(fonti_deboli)} fonti con score debole da confrontare.")
    if quesiti_aperti:
        avvisi.append(f"{quesiti_aperti} quesiti aperti richiedono decisione umana.")
    if duplicati:
        avvisi.append(f"{len(duplicati)} possibili duplicati documentali.")
    if richieste_bassa_conf:
        avvisi.append(f"{len(richieste_bassa_conf)} richieste con confidenza bassa.")

    azioni = []
    for issue in red["issues"]:
        azioni.extend(_azioni_da_issue(issue))
    # De-duplica mantenendo priorita' e target.
    viste = set()
    azioni_uniche = []
    for az in azioni:
        key = (az["tipo"], az.get("fatto_id"), az.get("richiesta_id"))
        if key in viste:
            continue
        viste.add(key)
        azioni_uniche.append(az)

    quality = {
        "score": max(0, min(100, 100 - len(blocchi) * 12 - len(avvisi) * 4)),
        "documenti_coperti": len(fonti_usate),
        "documenti_utilizzabili": len(doc_pronti),
        "copertura_documenti_percentuale": round(len(fonti_usate) / max(len(doc_pronti), 1) * 100),
        "richieste_totali": len(richieste),
        "richieste_confidenza_bassa": len(richieste_bassa_conf),
        "fonti_totali": len(fonti),
        "fonti_deboli": len(fonti_deboli),
        "fonti_assenti": len(righe_senza_fonti),
        "fonti_decisive": len(fonti_decisive),
        "quesiti_aperti": quesiti_aperti,
        "coerenze_da_rivedere": len(contraddizioni),
        "progressi": _progress_snapshot(lavoro),
    }

    prove_chiave = sorted(fonti, key=lambda f: float(f.get("score") or 0), reverse=True)[:5]
    dashboard = {
        "oggetto": lavoro.titolo,
        "stato": lavoro.stato,
        "parti_placeholder": sorted(lavoro.mappa_entita.keys())[:12],
        "domande": [
            {
                "id": r.id,
                "parte": r.parte_richiedente,
                "tipo": r.tipo,
                "testo": r.testo,
                "confidence": r.confidence,
            }
            for r in richieste[:12]
        ],
        "prove_chiave": prove_chiave,
        "punti_controversi": [
            lacuna
            for riga in righe_data
            for lacuna in riga.get("lacune", [])
        ][:10],
        "rischi": red["issues"][:8],
        "prossime_azioni": azioni_uniche[:8],
    }

    privacy_assistita = {
        "ok": privacy["ok"],
        "report": privacy,
        "entita": [
            {"placeholder": k, "valore": v}
            for k, v in sorted((lavoro.mappa_entita or {}).items())
        ],
        "placeholder_sospetti": privacy["malformed_placeholders"],
        "residui_sospetti": privacy["leaks"] + privacy["unknown_pii"],
    }

    return {
        "pronto_export": not blocchi,
        "messaggio": "Fascicolo pronto per l'export." if not blocchi else "Fascicolo non pronto per l'export.",
        "blocchi": blocchi,
        "avvisi": avvisi,
        "dashboard": dashboard,
        "checklist": [
            {"id": "documenti", "label": "Documenti accettati", "ok": bool(doc_pronti) and not doc_da_verificare and not doc_in_lavorazione},
            {"id": "richieste", "label": "Richieste estratte", "ok": bool(richieste) and lavoro.analisi_stato == Lavoro.StatoAnalisi.COMPLETATA},
            {"id": "fonti", "label": "Fonti confrontate", "ok": not righe_senza_fonti and not fonti_deboli},
            {"id": "quesiti", "label": "Quesiti aperti gestiti", "ok": quesiti_aperti == 0},
            {"id": "pqm", "label": "P.Q.M. compilato", "ok": bool(bozza and bozza.pqm.strip())},
            {"id": "privacy", "label": "Privacy pulita", "ok": privacy["ok"]},
            {"id": "red_team", "label": "Red-team senza criticita' alte", "ok": red["conteggi"]["alta"] == 0},
        ],
        "qualita_ai": quality,
        "red_team": red,
        "azioni_lacune": azioni_uniche,
        "privacy_assistita": privacy_assistita,
        "documenti_workflow": {
            "totali": len(documenti),
            "accettati": len(doc_pronti),
            "da_verificare": len(doc_da_verificare),
            "in_lavorazione": len(doc_in_lavorazione),
            "duplicati_sospetti": duplicati,
            "ordine_cronologico": [
                {
                    "id": d.id,
                    "nome": (d.file.name or "").rsplit("/", 1)[-1],
                    "nome_logico": d.nome_logico,
                    "ordine": d.ordine,
                    "sezione": d.sezione.tipo,
                    "tipo_rilevato": d.tipo_rilevato,
                    "created_at": d.created_at,
                }
                for d in sorted(documenti, key=lambda d: (d.ordine, d.created_at))
            ],
        },
        "template_disponibili": TEMPLATE_PROVVEDIMENTI,
    }


class AvviaAnalisiView(APIView):
    """Avvia l'analisi LLM del lavoro (asincrona)."""

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        if resp := _fase_gia_in_corso(lavoro, "analisi_stato", "Analisi"):
            return resp
        if not documenti_utilizzabili(lavoro).exists():
            return Response(
                {"detail": "Nessun documento utilizzabile: caricane e accettane almeno uno."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        non_accettati = _documenti_da_verificare(lavoro).count()
        if non_accettati and not request.data.get("conferma_parziale"):
            return Response(
                {
                    "detail": (
                        f"Ci sono {non_accettati} documenti pseudonimizzati non ancora "
                        "accettati. Conferma esplicitamente l'analisi parziale o rivedili prima."
                    ),
                    "code": "analisi_parziale_da_confermare",
                    "documenti_non_accettati": non_accettati,
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            commerciale, warning = _opt_in_commerciale(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        _marca_in_corso(
            lavoro,
            "analisi_stato",
            "analisi_errore",
            "analisi_progresso",
            "Analisi avviata",
        )
        res = analizza_lavoro_task.delay(lavoro.id, commerciale)
        _salva_task_id_se_ancora_in_corso(lavoro, "analisi_stato", "analisi_task_id", res.id)
        return Response(
            {
                "detail": "Analisi avviata.",
                "analisi_stato": Lavoro.StatoAnalisi.IN_CORSO,
                "warning": warning,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ApprofondisciView(APIView):
    """Avvia il ragionamento 'in diritto' su tutte le richieste del lavoro (M2)."""

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        if resp := _fase_gia_in_corso(lavoro, "approfondimento_stato", "Approfondimento"):
            return resp
        if not lavoro.richieste.exists():
            return Response(
                {"detail": "Nessuna richiesta: esegui prima l'analisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            commerciale, warning = _opt_in_commerciale(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        _marca_in_corso(
            lavoro,
            "approfondimento_stato",
            "approfondimento_errore",
            "approfondimento_progresso",
            "Approfondimento avviato",
        )
        res = approfondisci_lavoro_task.delay(lavoro.id, commerciale)
        _salva_task_id_se_ancora_in_corso(
            lavoro, "approfondimento_stato", "approfondimento_task_id", res.id
        )
        return Response(
            {
                "detail": "Approfondimento avviato.",
                "approfondimento_stato": Lavoro.StatoAnalisi.IN_CORSO,
                "warning": warning,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class AvviaRicercaView(APIView):
    """Avvia la ricerca giuridica 'spunti' via web (§6, async)."""

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        if resp := _fase_gia_in_corso(lavoro, "ricerca_stato", "Ricerca"):
            return resp
        try:
            commerciale, warning = _opt_in_commerciale(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        _marca_in_corso(
            lavoro,
            "ricerca_stato",
            "ricerca_errore",
            "ricerca_progresso",
            "Ricerca avviata",
        )
        res = ricerca_spunti_task.delay(lavoro.id, commerciale)
        _salva_task_id_se_ancora_in_corso(lavoro, "ricerca_stato", "ricerca_task_id", res.id)
        return Response(
            {
                "detail": "Ricerca avviata.",
                "ricerca_stato": Lavoro.StatoAnalisi.IN_CORSO,
                "warning": warning,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class RicercaManualeView(APIView):
    """Sintetizza uno spunto dai risultati incollati manualmente (§137)."""

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        if resp := _fase_gia_in_corso(lavoro, "ricerca_stato", "Ricerca"):
            return resp
        materiale = (request.data.get("materiale") or "").strip()
        if not materiale:
            return Response(
                {"detail": "Incolla i risultati nel campo 'materiale'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            commerciale, warning = _opt_in_commerciale(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        _marca_in_corso(
            lavoro,
            "ricerca_stato",
            "ricerca_errore",
            "ricerca_progresso",
            "Sintesi manuale avviata",
        )
        res = ricerca_manuale_task.delay(
            lavoro.id, (request.data.get("argomento") or "").strip(), materiale, commerciale
        )
        _salva_task_id_se_ancora_in_corso(lavoro, "ricerca_stato", "ricerca_task_id", res.id)
        return Response(
            {"detail": "Spunto in elaborazione.", "warning": warning},
            status=status.HTTP_202_ACCEPTED,
        )


# Fase -> (campo task_id, campo stato, campo errore) sul modello Lavoro.
FASI_ANNULLABILI = {
    "analisi": (
        "analisi_task_id",
        "analisi_stato",
        "analisi_errore",
        "analisi_progresso",
    ),
    "approfondimento": (
        "approfondimento_task_id",
        "approfondimento_stato",
        "approfondimento_errore",
        "approfondimento_progresso",
    ),
    "ricerca": (
        "ricerca_task_id",
        "ricerca_stato",
        "ricerca_errore",
        "ricerca_progresso",
    ),
}


class AnnullaAnalisiView(APIView):
    """Interrompe un'elaborazione in corso revocando il task Celery (§82).

    Utile se l'utente l'ha avviata per errore o vuole prima modificare i documenti.
    Riporta la fase a 'in attesa' così può essere rilanciata.
    """

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        fase = request.data.get("fase")
        if fase not in FASI_ANNULLABILI:
            return Response(
                {"detail": "Fase non valida: usa 'analisi', 'approfondimento' o 'ricerca'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        campo_task, campo_stato, campo_errore, campo_progresso = FASI_ANNULLABILI[fase]

        task_id = getattr(lavoro, campo_task)
        if task_id:
            # terminate=True ferma anche il task già in esecuzione (non solo in coda).
            current_app.control.revoke(task_id, terminate=True, signal="SIGTERM")

        # Rilegge lo stato fresco dal DB: il task potrebbe essersi concluso tra il
        # caricamento del lavoro e ora; senza questo scriveremmo 'in attesa' sopra
        # un esito 'completata' già persistito (race), perdendolo nella UI.
        lavoro.refresh_from_db(fields=[campo_stato])

        campi = [campo_task]
        setattr(lavoro, campo_task, "")
        # Riporta a 'in attesa' solo se è davvero in corso: evita di azzerare un
        # esito appena concluso (race tra revoke e completamento del task).
        if getattr(lavoro, campo_stato) == Lavoro.StatoAnalisi.IN_CORSO:
            setattr(lavoro, campo_stato, Lavoro.StatoAnalisi.IN_ATTESA)
            setattr(lavoro, campo_errore, "")
            setattr(
                lavoro,
                campo_progresso,
                {
                    "fase": "interrotta",
                    "corrente": 0,
                    "totale": 1,
                    "percentuale": 0,
                    "messaggio": "Elaborazione interrotta dall'utente",
                },
            )
            campi += [campo_stato, campo_errore, campo_progresso]
        lavoro.save(update_fields=campi)
        return Response({"detail": "Elaborazione interrotta."}, status=status.HTTP_200_OK)


class SpuntiListView(ListAPIView):
    """Elenco degli spunti di approfondimento del lavoro."""

    serializer_class = SpuntoRicercaSerializer

    def get_queryset(self):
        lavoro = _lavoro_utente(self.request, self.kwargs["lavoro_id"])
        return SpuntoRicerca.objects.filter(lavoro=lavoro)


class RichiesteListView(ListAPIView):
    """Elenco strutturato delle richieste analizzate di un lavoro."""

    serializer_class = RichiestaSerializer

    def get_queryset(self):
        lavoro = _lavoro_utente(self.request, self.kwargs["lavoro_id"])
        return Richiesta.objects.filter(lavoro=lavoro)


class MatriceLavoroView(ListAPIView):
    """Matrice richiesta -> fatto -> prova/lacuna del lavoro."""

    serializer_class = FattoProcessualeSerializer

    def get_queryset(self):
        lavoro = _lavoro_utente(self.request, self.kwargs["lavoro_id"])
        _sincronizza_matrice_lavoro(lavoro)
        return (
            FattoProcessuale.objects.filter(richiesta__lavoro=lavoro)
            .select_related("richiesta", "richiesta__lavoro")
            .prefetch_related("richiesta__allegati_collegati")
            .order_by("richiesta__ordine", "ordine", "id")
        )


class EventiDecisioneListView(ListAPIView):
    """Registro decisionale umano del lavoro."""

    serializer_class = EventoDecisionaleSerializer

    def get_queryset(self):
        lavoro = _lavoro_utente(self.request, self.kwargs["lavoro_id"])
        return EventoDecisionale.objects.filter(lavoro=lavoro).select_related(
            "utente", "richiesta", "fatto"
        )


class RichiestaUpdateView(APIView):
    """Editor: l'operatore redige la motivazione 'in diritto' di una richiesta (§1)."""

    def patch(self, request, pk):
        richiesta = get_object_or_404(Richiesta, pk=pk, lavoro__utente=request.user)
        motivazione = request.data.get("motivazione")
        if motivazione is not None:
            precedente = richiesta.motivazione
            richiesta.motivazione = motivazione
            richiesta.save(update_fields=["motivazione"])
            if precedente != motivazione:
                _registra_evento(
                    lavoro=richiesta.lavoro,
                    utente=request.user,
                    tipo=EventoDecisionale.Tipo.MOTIVAZIONE_AGGIORNATA,
                    richiesta=richiesta,
                    campo="motivazione",
                    descrizione="Motivazione in diritto aggiornata.",
                    valore_precedente={"motivazione": precedente},
                    valore_nuovo={"motivazione": motivazione},
                )
        return Response(RichiestaSerializer(richiesta).data)


class ApprofondisciRichiestaView(APIView):
    """Rilancia l'approfondimento solo su una richiesta."""

    def post(self, request, pk):
        richiesta = get_object_or_404(Richiesta, pk=pk, lavoro__utente=request.user)
        if resp := _fase_gia_in_corso(
            richiesta.lavoro, "approfondimento_stato", "Approfondimento"
        ):
            return resp
        try:
            commerciale, warning = _opt_in_commerciale(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        richiesta.lavoro.approfondimento_stato = Lavoro.StatoAnalisi.IN_CORSO
        richiesta.lavoro.approfondimento_errore = ""
        richiesta.lavoro.approfondimento_progresso = {
            "fase": "richiesta_singola",
            "corrente": 0,
            "totale": 1,
            "percentuale": 0,
            "messaggio": f"Ricalcolo richiesta {richiesta.ordine + 1}",
        }
        richiesta.lavoro.save(
            update_fields=[
                "approfondimento_stato",
                "approfondimento_errore",
                "approfondimento_progresso",
            ]
        )
        res = approfondisci_richiesta_task.delay(richiesta.id, commerciale)
        _salva_task_id_se_ancora_in_corso(
            richiesta.lavoro, "approfondimento_stato", "approfondimento_task_id", res.id
        )
        return Response(
            {
                "detail": "Approfondimento richiesta avviato.",
                "approfondimento_stato": Lavoro.StatoAnalisi.IN_CORSO,
                "warning": warning,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class FonteRichiestaView(APIView):
    """Marca una fonte interna come decisiva, irrilevante o da verificare."""

    VALORI = {
        "decisiva": "Decisiva",
        "irrilevante": "Irrilevante",
        "da_verificare": "Da verificare",
    }

    def patch(self, request, pk):
        richiesta = get_object_or_404(Richiesta, pk=pk, lavoro__utente=request.user)
        anchor = str(request.data.get("anchor") or "")
        valutazione = str(request.data.get("valutazione_operatore") or "")
        if valutazione not in self.VALORI:
            return Response(
                {"detail": "Valutazione non valida."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        fonti = list(richiesta.fonti_tracciate or RichiestaSerializer(richiesta).data["fonti_tracciate"])
        aggiornata = False
        for fonte in fonti:
            if isinstance(fonte, dict) and fonte.get("anchor") == anchor:
                fonte["valutazione_operatore"] = valutazione
                fonte["valutazione_label"] = self.VALORI[valutazione]
                aggiornata = True
        if not aggiornata:
            return Response({"detail": "Fonte non trovata."}, status=status.HTTP_404_NOT_FOUND)
        richiesta.fonti_tracciate = fonti
        richiesta.save(update_fields=["fonti_tracciate"])
        _registra_evento(
            lavoro=richiesta.lavoro,
            utente=request.user,
            tipo=EventoDecisionale.Tipo.FONTE_AGGIORNATA,
            richiesta=richiesta,
            campo=anchor,
            descrizione=f"Fonte marcata come {self.VALORI[valutazione].lower()}.",
            valore_nuovo={"anchor": anchor, "valutazione_operatore": valutazione},
        )
        return Response(RichiestaSerializer(richiesta).data)


class FattoProcessualeUpdateView(APIView):
    """Aggiorna la valutazione umana di una riga della matrice prove."""

    def patch(self, request, pk):
        fatto = get_object_or_404(
            FattoProcessuale,
            pk=pk,
            richiesta__lavoro__utente=request.user,
        )
        campi_tracciati = {
            "testo",
            "stato_prova",
            "funzione_prevalente",
            "stato_contraddittorio",
            "note_operatore",
            "note_contraddittorio",
            "quesito_umano",
        }
        precedente = {c: getattr(fatto, c) for c in campi_tracciati}
        serializer = FattoProcessualeSerializer(fatto, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        fatto.refresh_from_db()
        nuovo = {c: getattr(fatto, c) for c in campi_tracciati}
        cambiati = {c: {"prima": precedente[c], "dopo": nuovo[c]} for c in campi_tracciati if precedente[c] != nuovo[c]}
        if cambiati:
            _registra_evento(
                lavoro=fatto.richiesta.lavoro,
                utente=request.user,
                tipo=EventoDecisionale.Tipo.MATRICE_AGGIORNATA,
                richiesta=fatto.richiesta,
                fatto=fatto,
                campo=", ".join(sorted(cambiati)),
                descrizione="Riga della matrice richieste/prove aggiornata.",
                valore_precedente={c: v["prima"] for c, v in cambiati.items()},
                valore_nuovo={c: v["dopo"] for c, v in cambiati.items()},
            )
        return Response(serializer.data)


class RevisioneFascicoloView(APIView):
    """Report guidato pre-export: pronto/non pronto, lacune e qualita'."""

    def get(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        return Response(_report_revisione_lavoro(lavoro))


class ApplicaAzioneLacunaView(APIView):
    """Applica azioni operative semplici suggerite dalla revisione."""

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        tipo = str(request.data.get("tipo") or "")
        fatto = None
        richiesta = None
        if request.data.get("fatto_id"):
            fatto = get_object_or_404(
                FattoProcessuale,
                pk=request.data.get("fatto_id"),
                richiesta__lavoro=lavoro,
            )
            richiesta = fatto.richiesta
        elif request.data.get("richiesta_id"):
            richiesta = get_object_or_404(
                Richiesta, pk=request.data.get("richiesta_id"), lavoro=lavoro
            )

        descrizione = ""
        if tipo == "segna_insufficiente" and fatto:
            fatto.stato_prova = FattoProcessuale.StatoProva.INSUFFICIENTE
            fatto.note_operatore = (
                fatto.note_operatore
                or "Marcata insufficiente dalla revisione guidata: mancano fonti interne adeguate."
            )
            fatto.save(update_fields=["stato_prova", "note_operatore"])
            descrizione = "Riga marcata come prova insufficiente."
        elif tipo == "segna_da_verificare" and fatto:
            fatto.stato_prova = FattoProcessuale.StatoProva.DA_VERIFICARE
            fatto.save(update_fields=["stato_prova"])
            descrizione = "Riga mantenuta da verificare."
        elif tipo == "crea_quesito" and fatto:
            testo = (
                request.data.get("testo")
                or "Verificare manualmente se la richiesta e' sorretta da fonti interne sufficienti."
            )
            fatto.quesito_umano = testo
            fatto.save(update_fields=["quesito_umano"])
            quesiti = list(richiesta.quesiti_aperti or [])
            if testo not in quesiti:
                quesiti.append(testo)
                richiesta.quesiti_aperti = quesiti
                richiesta.save(update_fields=["quesiti_aperti"])
            descrizione = "Quesito umano aggiunto."
        elif tipo in {"integra_motivazione", "compila_pqm", "chiedi_ctu", "verifica_fonti", "cerca_fascicolo"}:
            testi_default = {
                "integra_motivazione": "Integrare la motivazione prima dell'export.",
                "compila_pqm": "Compilare o riallineare il P.Q.M. rispetto alle motivazioni.",
                "chiedi_ctu": "Valutare se formulare un quesito tecnico/CTU sui fatti controversi.",
                "verifica_fonti": "Verificare manualmente pertinenza e affidabilita' degli snippet.",
                "cerca_fascicolo": "Cercare nel fascicolo una fonte interna non ancora agganciata.",
            }
            CommentoEditor.objects.create(
                lavoro=lavoro,
                utente=request.user,
                sezione=CommentoEditor.Sezione.IN_DIRITTO
                if tipo != "compila_pqm"
                else CommentoEditor.Sezione.PQM,
                riferimento_id=getattr(richiesta, "id", None),
                testo=request.data.get("testo") or testi_default[tipo],
            )
            descrizione = testi_default[tipo]
        else:
            return Response(
                {"detail": "Azione non applicabile a questo target."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _registra_evento(
            lavoro=lavoro,
            utente=request.user,
            tipo=EventoDecisionale.Tipo.AZIONE_LACUNA,
            richiesta=richiesta,
            fatto=fatto,
            campo=tipo,
            descrizione=descrizione,
            valore_nuovo={"tipo": tipo},
        )
        return Response(_report_revisione_lavoro(lavoro))


class CommentiEditorView(APIView):
    """Commenti redazionali su bozza, P.Q.M., fonti e privacy."""

    def get(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        commenti = CommentoEditor.objects.filter(lavoro=lavoro).select_related("utente")
        return Response(CommentoEditorSerializer(commenti, many=True).data)

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        serializer = CommentoEditorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        commento = serializer.save(lavoro=lavoro, utente=request.user)
        _registra_evento(
            lavoro=lavoro,
            utente=request.user,
            tipo=EventoDecisionale.Tipo.COMMENTO_EDITOR,
            campo=commento.sezione,
            descrizione="Commento editor aggiunto.",
            valore_nuovo={"commento_id": commento.id, "sezione": commento.sezione},
        )
        return Response(CommentoEditorSerializer(commento).data, status=status.HTTP_201_CREATED)


class CommentoEditorUpdateView(APIView):
    def patch(self, request, pk):
        commento = get_object_or_404(
            CommentoEditor, pk=pk, lavoro__utente=request.user
        )
        for campo in ("testo", "risolto", "sezione", "riferimento_id"):
            if campo in request.data:
                setattr(commento, campo, request.data[campo])
        commento.save()
        return Response(CommentoEditorSerializer(commento).data)


class TemplateProvvedimentiView(APIView):
    def get(self, request):
        return Response(TEMPLATE_PROVVEDIMENTI)


class BozzaView(APIView):
    """Restituisce la bozza 'in fatto' del lavoro."""

    def get(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        bozza = Bozza.objects.filter(lavoro=lavoro).first()
        if bozza is None:
            return Response(
                {"detail": "Bozza non ancora generata."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(BozzaSerializer(bozza).data)

    def patch(self, request, lavoro_id):
        """Editor: l'utente modifica la bozza 'in fatto' e/o il P.Q.M."""
        lavoro = _lavoro_utente(request, lavoro_id)
        bozza = get_object_or_404(Bozza, lavoro=lavoro)
        campi = []
        for campo in ("in_fatto", "pqm"):
            valore = request.data.get(campo)
            if valore is not None:
                precedente = getattr(bozza, campo)
                setattr(bozza, campo, valore)
                campi.append(campo)
                if precedente != valore:
                    _registra_evento(
                        lavoro=lavoro,
                        utente=request.user,
                        tipo=EventoDecisionale.Tipo.BOZZA_AGGIORNATA,
                        campo=campo,
                        descrizione=f"Campo bozza aggiornato: {campo}.",
                        valore_precedente={campo: precedente},
                        valore_nuovo={campo: valore},
                    )
        if campi:
            bozza.versione += 1
            bozza.save(update_fields=[*campi, "versione", "updated_at"])
        return Response(BozzaSerializer(bozza).data)


class EsportaAuditDocxView(APIView):
    """Scarica l'allegato audit della matrice e del registro decisionale."""

    def get(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        _sincronizza_matrice_lavoro(lavoro)
        contenuto = genera_audit_docx(lavoro)
        _registra_evento(
            lavoro=lavoro,
            utente=request.user,
            tipo=EventoDecisionale.Tipo.AUDIT_ESPORTATO,
            descrizione="Allegato audit esportato.",
        )
        resp = HttpResponse(contenuto, content_type=DOCX_CONTENT_TYPE)
        resp["Content-Disposition"] = f'attachment; filename="audit_lavoro_{lavoro.id}.docx"'
        return resp


class RedTeamFascicoloView(APIView):
    """Controllo critico su richieste, prove, motivazione e P.Q.M."""

    def post(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        report = _red_team_lavoro(lavoro)
        _registra_evento(
            lavoro=lavoro,
            utente=request.user,
            tipo=EventoDecisionale.Tipo.RED_TEAM_ESEGUITO,
            descrizione="Red team del fascicolo eseguito.",
            valore_nuovo={
                "totale": report["totale"],
                "conteggi": report["conteggi"],
            },
        )
        return Response(report)


class EsportaDocxView(APIView):
    """Scarica la bozza come documento Word (.docx) — §7."""

    def get(self, request, lavoro_id):
        lavoro = _lavoro_utente(request, lavoro_id)
        in_chiaro = request.query_params.get("chiaro") == "1"
        if not in_chiaro and request.query_params.get("force_privacy") != "1":
            testi = []
            bozza = Bozza.objects.filter(lavoro=lavoro).first()
            if bozza:
                testi.extend([bozza.in_fatto, bozza.pqm])
            for r in lavoro.richieste.all():
                testi.extend(
                    [
                        r.testo,
                        r.onere_probatorio,
                        r.motivazione,
                        "\n".join(
                            str(f.get("snippet", ""))
                            for f in (r.fonti_tracciate or [])
                            if isinstance(f, dict)
                        ),
                        "\n".join(r.non_contestazioni or []),
                        "\n".join(r.quesiti_aperti or []),
                    ]
                )
            mappa = lavoro.mappa_entita or {}
            testi = [maschera_residui(testo, mappa) for testo in testi]
            report = privacy_report(testi, mappa, extra_values=[lavoro.titolo])
            if not report["ok"]:
                return Response(
                    {
                        "detail": (
                            "Il controllo privacy segnala possibili residui. "
                            "Rivedi il testo o conferma esplicitamente l'override."
                        ),
                        "privacy_report": report,
                    },
                    status=status.HTTP_409_CONFLICT,
                )
        contenuto = genera_docx(lavoro, in_chiaro=in_chiaro)
        suffisso = "_in_chiaro" if in_chiaro else ""
        resp = HttpResponse(contenuto, content_type=DOCX_CONTENT_TYPE)
        resp["Content-Disposition"] = f'attachment; filename="bozza_{lavoro.id}{suffisso}.docx"'
        return resp
