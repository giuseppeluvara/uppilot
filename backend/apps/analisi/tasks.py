"""Task asincrono di analisi LLM (§82): la generazione è lunga -> fuori dalla richiesta."""
from __future__ import annotations

import logging
import re
from django.utils import timezone

from celery import shared_task
from django.db.models import Q

from ai.factory import (
    get_anonymization_service,
    get_embedding_backend,
    get_legal_search_provider,
    get_llm_backend,
)
from apps.casi.models import Lavoro
from apps.casi.privacy import maschera_residui
from apps.casi.states import StatoLavoro

from .models import Bozza, Richiesta, SpuntoRicerca
from .ricerca import (
    proponi_ricerche,
    pseudonimizza_query,
    sintetizza_spunto,
    _formatta_risultati,
)
from .services import analizza_lavoro, approfondisci_richiesta, documenti_utilizzabili

logger = logging.getLogger(__name__)


def _set_progress(
    lavoro: Lavoro,
    campo: str,
    fase: str,
    *,
    corrente: float = 0,
    totale: float = 1,
    messaggio: str = "",
) -> None:
    totale = max(float(totale or 1), 1.0)
    corrente = max(min(float(corrente or 0), totale), 0.0)
    setattr(
        lavoro,
        campo,
        {
            "fase": fase,
            "corrente": corrente,
            "totale": totale,
            "percentuale": round(corrente / totale * 100),
            "messaggio": messaggio,
            "aggiornato_at": timezone.now().isoformat(),
        },
    )
    lavoro.save(update_fields=[campo])


def _errore_operativo(exc: Exception) -> str:
    testo = str(exc)
    basso = testo.lower()
    if (
        "host.docker.internal" in basso
        or "11434" in basso
        or "network is unreachable" in basso
        or "connection refused" in basso
        or "connecterror" in basso
    ):
        return (
            "Ollama non raggiungibile dal worker/container. Avvia sul Mac con "
            "OLLAMA_HOST=0.0.0.0:11434 ollama serve oppure abilita il LaunchAgent "
            "com.uppilot.ollama; poi verifica OLLAMA_BASE_URL=http://host.docker.internal:11434."
        )
    return testo


def _sanifica_lavoro(lavoro: Lavoro, testo: str) -> str:
    return maschera_residui(testo or "", lavoro.mappa_entita or {})


def _sanifica_lista(lavoro: Lavoro, valori) -> list[str]:
    return [_sanifica_lavoro(lavoro, str(x)) for x in (valori or []) if x]


_NUMERO_SENSIBILE_RE = re.compile(
    r"(?:€\s*)?\b\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?\b|\b\d+/\d{2,4}\b|"
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    re.IGNORECASE,
)


def _numeri_sensibili(testo: str) -> set[str]:
    return {re.sub(r"\s+", "", m.group(0).replace("€", "")) for m in _NUMERO_SENSIBILE_RE.finditer(testo or "")}


def _avvisi_coerenza_numerica(richiesta: Richiesta, *testi_generati: str) -> list[str]:
    sorgente = _numeri_sensibili(richiesta.testo)
    if not sorgente:
        return []
    generati: set[str] = set()
    for testo in testi_generati:
        generati |= _numeri_sensibili(testo)
    estranei = sorted(generati - sorgente)
    if not estranei:
        return []
    return [
        "Numeri/importi generati non presenti nel testo della richiesta: "
        + ", ".join(estranei[:5])
        + ". Verifica coerenza con gli atti."
    ]


def _pqm_scheletro(richieste: list[Richiesta]) -> str:
    if not richieste:
        return ""
    righe = ["P.Q.M.", "Il Giudice, ogni diversa domanda, eccezione e istanza disattesa o assorbita:"]
    parti = {
        Richiesta.Parte.ATTORE: "Attore",
        Richiesta.Parte.CONVENUTO: "Convenuto",
    }
    for indice, richiesta in enumerate(richieste, start=1):
        tipo = richiesta.get_tipo_display().lower()
        parte = parti.get(richiesta.parte_richiedente, richiesta.get_parte_richiedente_display())
        righe.append(
            f"{indice}. sulla {tipo} di parte {parte}: "
            f"[DA DECIDERE] {richiesta.testo}"
        )
    righe.append("Spese di lite: [DA DECIDERE].")
    return "\n".join(righe)


def _pqm_da_rigenerare(pqm: str) -> bool:
    testo = (pqm or "").strip()
    if not testo:
        return True
    return (
        "Convenuto/ricorrente" in testo
        and "[DA DECIDERE]" in testo
        and "Spese di lite:" in testo
        and "Il Giudice, ogni diversa domanda" in testo
    )


def _contenuto_per_richiesta(richieste: list[Richiesta]) -> dict[str, dict]:
    contenuto: dict[str, dict] = {}
    for richiesta in richieste:
        contenuto[str(richiesta.id)] = {
            "ordine": richiesta.ordine,
            "parte": richiesta.parte_richiedente,
            "tipo": richiesta.tipo,
            "testo": richiesta.testo,
            "onere_probatorio": richiesta.onere_probatorio,
            "motivazione": richiesta.motivazione,
            "non_contestazioni": richiesta.non_contestazioni or [],
            "quesiti_aperti": richiesta.quesiti_aperti or [],
            "allegati_collegati": list(
                richiesta.allegati_collegati.values_list("id", flat=True)
            ),
        }
    return contenuto


def _confidence(valore) -> float:
    try:
        return max(0.0, min(1.0, float(valore)))
    except (TypeError, ValueError):
        return 0.65


@shared_task
def analizza_lavoro_task(lavoro_id: int, commerciale: bool = False) -> None:
    lavoro = Lavoro.objects.get(pk=lavoro_id)
    lavoro.analisi_stato = Lavoro.StatoAnalisi.IN_CORSO
    lavoro.analisi_errore = ""
    lavoro.analisi_progresso = {
        "fase": "preparazione",
        "corrente": 0,
        "totale": 4,
        "percentuale": 0,
        "messaggio": "Preparazione dei documenti pseudonimizzati",
        "aggiornato_at": timezone.now().isoformat(),
    }
    lavoro.save(update_fields=["analisi_stato", "analisi_errore", "analisi_progresso"])

    try:
        _set_progress(
            lavoro,
            "analisi_progresso",
            "preparazione_llm",
            corrente=1,
            totale=4,
            messaggio="Preparazione del modello locale",
        )
        dati = analizza_lavoro(
            lavoro,
            get_llm_backend(commerciale),
            progress_callback=lambda fase, corrente, totale, messaggio: _set_progress(
                lavoro,
                "analisi_progresso",
                fase,
                corrente=corrente,
                totale=totale,
                messaggio=messaggio,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Analisi fallita per il lavoro %s", lavoro_id)
        messaggio = _errore_operativo(exc)
        lavoro.analisi_stato = Lavoro.StatoAnalisi.ERRORE
        lavoro.analisi_errore = messaggio
        lavoro.analisi_task_id = ""
        lavoro.analisi_progresso = {
            "fase": "errore",
            "corrente": 0,
            "totale": 1,
            "percentuale": 0,
            "messaggio": messaggio,
            "aggiornato_at": timezone.now().isoformat(),
        }
        lavoro.save(
            update_fields=[
                "analisi_stato",
                "analisi_errore",
                "analisi_task_id",
                "analisi_progresso",
            ]
        )
        return

    _set_progress(
        lavoro,
        "analisi_progresso",
        "salvataggio",
        corrente=3,
        totale=4,
        messaggio="Salvataggio di bozza e griglia richieste",
    )
    dati["in_fatto"] = _sanifica_lavoro(lavoro, dati.get("in_fatto", ""))
    for richiesta in dati.get("richieste", []):
        richiesta["testo"] = _sanifica_lavoro(lavoro, richiesta.get("testo", ""))
        richiesta["quesiti_aperti"] = _sanifica_lista(
            lavoro, richiesta.get("quesiti_aperti", [])
        )

    # Persiste la bozza "in fatto".
    Bozza.objects.update_or_create(
        lavoro=lavoro, defaults={"in_fatto": dati["in_fatto"]}
    )

    # Rigenera l'elenco strutturato delle richieste.
    lavoro.richieste.all().delete()
    Richiesta.objects.bulk_create(
        Richiesta(
            lavoro=lavoro,
            parte_richiedente=r["parte"],
            tipo=r.get("tipo", Richiesta.Tipo.DOMANDA),
            testo=r["testo"],
            confidence=_confidence(r.get("confidence", 0.65)),
            flags=r.get("flags", []),
            quesiti_aperti=r["quesiti_aperti"],
            stato=Richiesta.Stato.ANALIZZATA,
            ordine=i,
        )
        for i, r in enumerate(dati["richieste"])
    )

    # Avanzamento della state machine: analizzato -> bozza generata (§45).
    if lavoro.stato == StatoLavoro.BOZZA_IN_CORSO:
        lavoro.transiziona(StatoLavoro.ANALIZZATO)
    if lavoro.stato == StatoLavoro.ANALIZZATO:
        lavoro.transiziona(StatoLavoro.BOZZA_GENERATA)

    lavoro.analisi_stato = Lavoro.StatoAnalisi.COMPLETATA
    lavoro.analisi_task_id = ""
    lavoro.analisi_progresso = {
        "fase": "completata",
        "corrente": 4,
        "totale": 4,
        "percentuale": 100,
        "messaggio": "Analisi completata",
        "aggiornato_at": timezone.now().isoformat(),
    }
    lavoro.save(update_fields=["analisi_stato", "analisi_task_id", "analisi_progresso"])


def _riferimenti_corpus(lavoro: Lavoro, testo: str) -> str:
    """Recupera spunti dal corpus per la richiesta (RAG, §83).

    Graceful: se il corpus è vuoto, l'embedding non è disponibile o qualcosa va
    storto, ritorna stringa vuota senza interrompere l'analisi.
    """
    try:
        from apps.corpus.services import cerca
        from apps.corpus.models import DocumentoCorpus

        documenti = DocumentoCorpus.objects.filter(
            Q(creato_da__isnull=True) | Q(creato_da_id=lavoro.utente_id)
        )
        frammenti = cerca(testo, get_embedding_backend(), k=3, documenti=documenti)
        if not frammenti:
            return ""
        return "\n".join(
            f"- [{f.documento.titolo}] {f.testo.strip()[:300]}" for f in frammenti
        )
    except Exception:  # noqa: BLE001 - il RAG è un di più, mai bloccante
        logger.warning("RAG non disponibile per l'approfondimento", exc_info=True)
        return ""


@shared_task
def approfondisci_lavoro_task(lavoro_id: int, commerciale: bool = False) -> None:
    """Ragionamento 'in diritto' su tutte le richieste del lavoro (M2)."""
    lavoro = Lavoro.objects.get(pk=lavoro_id)
    lavoro.approfondimento_stato = Lavoro.StatoAnalisi.IN_CORSO
    lavoro.approfondimento_errore = ""
    richieste = list(lavoro.richieste.all())
    lavoro.approfondimento_progresso = {
        "fase": "preparazione",
        "corrente": 0,
        "totale": max(len(richieste), 1),
        "percentuale": 0,
        "messaggio": "Preparazione richieste e documenti",
        "aggiornato_at": timezone.now().isoformat(),
    }
    lavoro.save(
        update_fields=[
            "approfondimento_stato",
            "approfondimento_errore",
            "approfondimento_progresso",
        ]
    )

    documenti = list(documenti_utilizzabili(lavoro))
    try:
        llm = get_llm_backend(commerciale)
        totale = max(len(richieste), 1)
        for indice, richiesta in enumerate(richieste, start=1):
            _set_progress(
                lavoro,
                "approfondimento_progresso",
                "richiesta",
                corrente=indice - 0.5,
                totale=totale,
                messaggio=f"Approfondimento domanda {indice}/{len(richieste)}",
            )
            riferimenti = _riferimenti_corpus(lavoro, richiesta.testo)
            dati = approfondisci_richiesta(richiesta, documenti, llm, riferimenti)
            richiesta.onere_probatorio = _sanifica_lavoro(
                lavoro, dati["onere_probatorio"]
            )
            richiesta.motivazione = _sanifica_lavoro(lavoro, dati["motivazione"])
            richiesta.non_contestazioni = _sanifica_lista(
                lavoro, dati["non_contestazioni"]
            )
            richiesta.quesiti_aperti = _sanifica_lista(lavoro, dati["quesiti_aperti"])
            flags = list(richiesta.flags or [])
            flags.extend(
                _avvisi_coerenza_numerica(
                    richiesta,
                    richiesta.onere_probatorio,
                    richiesta.motivazione,
                    "\n".join(richiesta.non_contestazioni or []),
                    "\n".join(richiesta.quesiti_aperti or []),
                )
            )
            if len(dati["allegati"]) > 3:
                flags.append("Allegati collegati oltre la soglia attesa: rivedi pertinenza.")
            richiesta.flags = list(dict.fromkeys(flags))
            richiesta.stato = Richiesta.Stato.APPROFONDITA
            richiesta.save(
                update_fields=[
                    "onere_probatorio",
                    "motivazione",
                    "non_contestazioni",
                    "quesiti_aperti",
                    "flags",
                    "stato",
                ]
            )
            richiesta.allegati_collegati.set(dati["allegati"])
            _set_progress(
                lavoro,
                "approfondimento_progresso",
                "richiesta",
                corrente=indice,
                totale=totale,
                messaggio=f"Domanda {indice}/{len(richieste)} completata",
            )
        bozza, _ = Bozza.objects.get_or_create(lavoro=lavoro)
        richieste_aggiornate = list(
            lavoro.richieste.prefetch_related("allegati_collegati").all()
        )
        update_fields = ["contenuto_per_richiesta", "versione", "updated_at"]
        bozza.contenuto_per_richiesta = _contenuto_per_richiesta(richieste_aggiornate)
        if _pqm_da_rigenerare(bozza.pqm):
            bozza.pqm = _sanifica_lavoro(lavoro, _pqm_scheletro(richieste_aggiornate))
            update_fields.append("pqm")
        bozza.versione += 1
        bozza.save(update_fields=update_fields)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Approfondimento fallito per il lavoro %s", lavoro_id)
        messaggio = _errore_operativo(exc)
        lavoro.approfondimento_stato = Lavoro.StatoAnalisi.ERRORE
        lavoro.approfondimento_errore = messaggio
        lavoro.approfondimento_task_id = ""
        lavoro.approfondimento_progresso = {
            "fase": "errore",
            "corrente": 0,
            "totale": 1,
            "percentuale": 0,
            "messaggio": messaggio,
            "aggiornato_at": timezone.now().isoformat(),
        }
        lavoro.save(
            update_fields=[
                "approfondimento_stato",
                "approfondimento_errore",
                "approfondimento_task_id",
                "approfondimento_progresso",
            ]
        )
        return

    lavoro.approfondimento_stato = Lavoro.StatoAnalisi.COMPLETATA
    lavoro.approfondimento_task_id = ""
    lavoro.approfondimento_progresso = {
        "fase": "completata",
        "corrente": max(len(richieste), 1),
        "totale": max(len(richieste), 1),
        "percentuale": 100,
        "messaggio": "Approfondimento completato",
        "aggiornato_at": timezone.now().isoformat(),
    }
    lavoro.save(
        update_fields=[
            "approfondimento_stato",
            "approfondimento_task_id",
            "approfondimento_progresso",
        ]
    )


@shared_task
def ricerca_spunti_task(lavoro_id: int, commerciale: bool = False) -> None:
    """Ricerca giuridica 'spunti' via web search (§6). Query pseudonimizzata (§134)."""
    lavoro = Lavoro.objects.get(pk=lavoro_id)
    lavoro.ricerca_stato = Lavoro.StatoAnalisi.IN_CORSO
    lavoro.ricerca_errore = ""
    lavoro.ricerca_progresso = {
        "fase": "preparazione",
        "corrente": 0,
        "totale": 3,
        "percentuale": 0,
        "messaggio": "Preparazione delle query giuridiche",
        "aggiornato_at": timezone.now().isoformat(),
    }
    lavoro.save(update_fields=["ricerca_stato", "ricerca_errore", "ricerca_progresso"])

    try:
        llm = get_llm_backend(commerciale)
        provider = get_legal_search_provider()
        anon = get_anonymization_service()

        _set_progress(
            lavoro,
            "ricerca_progresso",
            "query",
            corrente=0,
            totale=3,
            messaggio="Generazione query pseudonimizzate",
        )
        ricerche = proponi_ricerche(lavoro, llm)
        lavoro.spunti.filter(origine=SpuntoRicerca.Origine.WEB).delete()
        totale = max(len(ricerche), 1)
        for indice, ricerca in enumerate(ricerche, start=1):
            _set_progress(
                lavoro,
                "ricerca_progresso",
                "web",
                corrente=indice - 1,
                totale=totale,
                messaggio=f"Ricerca fonte {indice}/{len(ricerche)}",
            )
            query = pseudonimizza_query(ricerca["query"], anon)
            risultati = provider.search(query)
            risultati_con_fonte = [r for r in risultati if getattr(r, "fonte", "")]
            if not risultati_con_fonte:
                SpuntoRicerca.objects.create(
                    lavoro=lavoro,
                    query_pseudonimizzata=query,
                    argomento=ricerca["argomento"],
                    sintesi=(
                        "Ricerca insufficiente: il provider non ha restituito fonti "
                        "verificabili per questa query."
                    ),
                    suggerimento=(
                        "Riformula la query con istituto giuridico, norma o orientamento "
                        "più specifico, oppure incolla manualmente risultati da una fonte affidabile."
                    ),
                    fonte="",
                    stato_fonte=SpuntoRicerca.StatoFonte.INSUFFICIENTE,
                    origine=SpuntoRicerca.Origine.WEB,
                )
                _set_progress(
                    lavoro,
                    "ricerca_progresso",
                    "web",
                    corrente=indice,
                    totale=totale,
                    messaggio=f"Ricerca {indice}/{len(ricerche)} insufficiente",
                )
                continue
            dati = sintetizza_spunto(
                ricerca["argomento"], query, _formatta_risultati(risultati_con_fonte), llm
            )
            SpuntoRicerca.objects.create(
                lavoro=lavoro,
                query_pseudonimizzata=query,
                argomento=ricerca["argomento"],
                sintesi=_sanifica_lavoro(lavoro, dati["sintesi"]),
                suggerimento=_sanifica_lavoro(lavoro, dati["suggerimento"]),
                fonte=risultati_con_fonte[0].fonte,
                stato_fonte=SpuntoRicerca.StatoFonte.OK,
                origine=SpuntoRicerca.Origine.WEB,
            )
            _set_progress(
                lavoro,
                "ricerca_progresso",
                "web",
                corrente=indice,
                totale=totale,
                messaggio=f"Spunto {indice}/{len(ricerche)} creato",
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ricerca spunti fallita per il lavoro %s", lavoro_id)
        messaggio = _errore_operativo(exc)
        lavoro.ricerca_stato = Lavoro.StatoAnalisi.ERRORE
        lavoro.ricerca_errore = messaggio
        lavoro.ricerca_task_id = ""
        lavoro.ricerca_progresso = {
            "fase": "errore",
            "corrente": 0,
            "totale": 1,
            "percentuale": 0,
            "messaggio": messaggio,
            "aggiornato_at": timezone.now().isoformat(),
        }
        lavoro.save(
            update_fields=[
                "ricerca_stato",
                "ricerca_errore",
                "ricerca_task_id",
                "ricerca_progresso",
            ]
        )
        return

    lavoro.ricerca_stato = Lavoro.StatoAnalisi.COMPLETATA
    lavoro.ricerca_task_id = ""
    lavoro.ricerca_progresso = {
        "fase": "completata",
        "corrente": 1,
        "totale": 1,
        "percentuale": 100,
        "messaggio": "Ricerca completata",
        "aggiornato_at": timezone.now().isoformat(),
    }
    lavoro.save(update_fields=["ricerca_stato", "ricerca_task_id", "ricerca_progresso"])


@shared_task
def ricerca_manuale_task(
    lavoro_id: int, argomento: str, materiale: str, commerciale: bool = False
) -> None:
    """Sintetizza uno spunto da risultati incollati manualmente dall'utente (§137)."""
    lavoro = Lavoro.objects.get(pk=lavoro_id)
    lavoro.ricerca_stato = Lavoro.StatoAnalisi.IN_CORSO
    lavoro.ricerca_errore = ""
    lavoro.ricerca_progresso = {
        "fase": "manuale",
        "corrente": 0,
        "totale": 2,
        "percentuale": 0,
        "messaggio": "Sintesi dei risultati incollati",
        "aggiornato_at": timezone.now().isoformat(),
    }
    lavoro.save(update_fields=["ricerca_stato", "ricerca_errore", "ricerca_progresso"])

    try:
        dati = sintetizza_spunto(
            argomento, "", materiale, get_llm_backend(commerciale), origine="manuale"
        )
        _set_progress(
            lavoro,
            "ricerca_progresso",
            "manuale",
            corrente=1,
            totale=2,
            messaggio="Salvataggio dello spunto manuale",
        )
        SpuntoRicerca.objects.create(
            lavoro=lavoro,
            argomento=argomento,
            sintesi=_sanifica_lavoro(lavoro, dati["sintesi"]),
            suggerimento=_sanifica_lavoro(lavoro, dati["suggerimento"]),
            origine=SpuntoRicerca.Origine.MANUALE,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ricerca manuale fallita per il lavoro %s", lavoro_id)
        messaggio = _errore_operativo(exc)
        lavoro.ricerca_stato = Lavoro.StatoAnalisi.ERRORE
        lavoro.ricerca_errore = messaggio
        lavoro.ricerca_task_id = ""
        lavoro.ricerca_progresso = {
            "fase": "errore",
            "corrente": 0,
            "totale": 1,
            "percentuale": 0,
            "messaggio": messaggio,
            "aggiornato_at": timezone.now().isoformat(),
        }
        lavoro.save(
            update_fields=[
                "ricerca_stato",
                "ricerca_errore",
                "ricerca_task_id",
                "ricerca_progresso",
            ]
        )
        return

    lavoro.ricerca_stato = Lavoro.StatoAnalisi.COMPLETATA
    lavoro.ricerca_task_id = ""
    lavoro.ricerca_progresso = {
        "fase": "completata",
        "corrente": 2,
        "totale": 2,
        "percentuale": 100,
        "messaggio": "Spunto manuale creato",
        "aggiornato_at": timezone.now().isoformat(),
    }
    lavoro.save(update_fields=["ricerca_stato", "ricerca_task_id", "ricerca_progresso"])
