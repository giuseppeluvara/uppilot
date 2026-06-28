# UPPilot

[![CI](https://github.com/giuseppeluvara/uppilot/actions/workflows/ci.yml/badge.svg)](https://github.com/giuseppeluvara/uppilot/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

> Assistente **open source, local-first e dockerizzato** alla redazione di **bozze di
> sentenza/parere** per gli **Uffici per il Processo (UPP)** del Ministero della Giustizia.

UPPilot **non sostituisce il giudizio umano**: è un *sintetizzatore*, un *organizzatore di
flusso* e un *consigliere*. Tutto ciò che è oggettivo lo scrive il sistema; tutto ciò che
richiede discernimento giuridico viene posto all'operatore come **interrogativo strutturato**,
mai come conclusione definitiva. La bozza resta sempre soggetta a revisione umana esterna alla
piattaforma.

Licenza: **AGPL-3.0-or-later**.

> 👤 **Sei un operatore (redattore UPP) e vuoi solo usare il programma?** Vai alla
> **[Guida operativa](GUIDA.md)** — avvio, uso passo per passo, spegnimento, backup e problemi
> comuni. Questo README è la documentazione tecnica/architetturale.

---

## ⚠️ Avvertenza privacy / GDPR (leggere prima dell'uso)

- Ogni documento caricato passa **obbligatoriamente** dal *Privacy Filter* prima di poter essere
  inviato a qualunque LLM.
- Il Privacy Filter esegue **pseudonimizzazione, NON anonimizzazione**: sotto il GDPR il dato
  pseudonimizzato **resta dato personale**. Non è una garanzia di conformità.
- Default su fascicoli reali: **LLM locale**. L'uso di LLM commerciali in cloud è possibile solo
  come **opt-in esplicito per singola azione**, sempre su testo pseudonimizzato. Non può essere
  abilitato globalmente con una variabile d'ambiente.

---

## Requisiti minimi di sistema (disclaimer)

Lo stack completo gira in locale via Docker. Indicazioni di massima:

| Risorsa | Minimo consigliato |
|---|---|
| RAM | **16 GB** (stack completo: Postgres + Redis + Django + worker + privacy-filter + LLM locale) |
| Disco | ~15–25 GB liberi per i pesi dei modelli |
| GPU | Opzionale ma **raccomandata** per uso reale su fascicoli (OCR/LLM più veloci) |

> I requisiti reali dipendono dai modelli scelti e dal volume dei fascicoli. Ambiente di
> riferimento per lo sviluppo: **Mac Apple Silicon (M4, 16 GB)**. Su Mac **Ollama gira sull'host**
> (per usare la GPU Metal) e i container lo raggiungono via `host.docker.internal`.

### Performance del Privacy Filter (CPU vs GPU)

Il servizio `privacy-filter` (modello `openai/privacy-filter`) è il componente più sensibile
all'hardware:

- **Su CPU** una singola anonimizzazione richiede ~1s; per evitare la contesa sui core quando
  si caricano più documenti insieme, l'inferenza è **serializzata** (un documento alla volta).
  Su fascicoli grandi questo è il principale collo di bottiglia.
- **Con GPU NVIDIA** la concorrenza non è un problema: avviare con l'override GPU
  (`make up-gpu`, che usa `docker-compose.gpu.yml` per il passthrough su `privacy-filter` e
  `ollama`). In produzione su volumi reali la **GPU è fortemente raccomandata**.
- L'anonimizzazione ha **retry automatico** (3 tentativi) ed è ri-lanciabile dal singolo
  documento ("Riprova") in caso di errore.

---

## Avvio rapido

```bash
cp .env.example .env            # adatta i valori
make license                    # scarica il testo canonico AGPL-3.0
make provision                  # scarica i pesi dei modelli (glm-ocr, LLM, privacy-filter)

# Mac Apple Silicon (Ollama sull'host):
OLLAMA_HOST=0.0.0.0:11434 ollama serve  # in un terminale a parte
make up-mac

# Linux/server con GPU NVIDIA:
make up-gpu
```

Servizi esposti in dev: frontend `:5173`, backend API `:8000`, privacy-filter `:8001`.

### Mac: servizi locali al riavvio

Su Mac Ollama gira sull'host, non nel `docker-compose`, quindi deve ascoltare su tutte le
interfacce locali per essere raggiungibile dai container:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
curl http://localhost:11434/api/tags
docker compose exec -T worker python - <<'PY'
import urllib.request
urllib.request.urlopen("http://host.docker.internal:11434/api/tags", timeout=5)
print("Ollama raggiungibile dal worker")
PY
```

Nel workspace sono presenti script richiamabili da LaunchAgent utente:

- `scripts/uppilot-redis-at-login.sh`: riattiva il Redis del progetto dopo il login;
- `scripts/uppilot-stack-at-login.sh`: avvia l'intero stack Docker UPPilot dopo il login.

Entrambi attendono Docker Desktop se non è ancora pronto. In questa macchina sono stati configurati
i LaunchAgent utente `com.uppilot.ollama` (Ollama persistente), `com.uppilot.redis` (Redis del
compose) e `com.uppilot.stack` (stack UPPilot completo).

### Accesso dalla rete locale

Sul Mac mini di sviluppo UPPilot è pubblicato anche sulla LAN:

- `http://mac-mini.local:5173`
- `http://192.168.1.62:5173`

Il nome Bonjour è `mac-mini.local`; il Wi-Fi è configurato manualmente su `192.168.1.62/24` con
router/DNS `192.168.1.1`. Per una configurazione ancora più robusta è preferibile replicare questa
assegnazione come prenotazione DHCP sul router per il MAC Wi-Fi `1c:f6:4c:46:20:f4`.

La UI espone inoltre un preflight ambiente (`/api/health/ai/`) che controlla DB, Redis,
privacy-filter, Ollama e modelli configurati prima di lanciare task lunghi.

---

## Architettura (sintesi)

Monolite **Django + DRF** che comunica con i servizi AI **solo via HTTP**, dietro astrazioni
(`OCRBackend`, `LLMBackend`, `AnonymizationService`, `LegalSearchProvider`). Nessuna libreria ML
importata in-process nell'app Django.

```
React SPA ──REST──> Django + DRF ──HTTP──> Ollama (GLM-OCR + LLM + embeddings locali)
                          │      ──HTTP──> Privacy Filter (openai/privacy-filter)
                          │      ──HTTPS─> LLM commerciale (SDK Anthropic, opt-in)
                          ├──> Postgres + pgvector   (RAG: ricerca semantica sul corpus)
                          └──> Redis + Celery (OCR / anonimizzazione / analisi asincrone)
```

Stack: **Django 5 + DRF**, **Celery + Redis**, **Postgres + pgvector**, **React + TypeScript +
Vite + shadcn/ui**. Dettaglio di scope e milestone: vedi `PROMPT_INIZIALE_assistente_bozze_upp.md`.

---

## Funzionalità

**M1** — login e gestione lavori; upload nelle 3 sezioni (attore / convenuto / generici),
estrazione testo da PDF nativo + **OCR** (GLM-OCR) con flag di bassa confidenza; **Privacy Filter
obbligatorio** (pseudonimizzazione) con flusso di verifica/accettazione e avviso GDPR persistente;
analisi LLM locale: sintesi **"in fatto"** + estrazione strutturata delle **richieste** delle parti;
editor; archivio storico.

**M2** — ragionamento **"in diritto"** per richiesta (tipo domanda/difesa/riconvenzionale/istanza,
onere probatorio, non contestazioni filtrate, allegati pertinenti, confidenza e avvisi di coerenza);
**export `.docx`** (anche versione "in chiaro" de-pseudonimizzata); **ricerca giuridica
"spunti"** (web o incolla manuale; la query esce sempre pseudonimizzata); **LLM commerciali opt-in**
(SDK Anthropic); **RAG** su pgvector (corpus globale o personale di normativa/giurisprudenza,
ricerca semantica a supporto dell'analisi "in diritto").

**Grafo della conoscenza** — mappa navigabile di istituti, riferimenti normativi e **casi
anonimizzati**, costruita dal **LLM locale** sul corpus e sull'analisi (solo testo pseudonimizzato).
Visualizzazione interattiva (community detection a colori, ForceAtlas2) con filtri, ricerca,
scope di ricostruzione, interruzione, changelog e pannello di dettaglio con origine/snippet. La
costruzione e la consultazione rispettano i permessi su casi e corpus.
Implementazione nativa ispirata a `nashsu/llm_wiki` (nessun codice GPL; solo librerie viz MIT).
È un ausilio alla consultazione, non una fonte di conclusioni (§1).

**Affinamenti** — etichette PII italiane (C.F. / P.IVA / IBAN / PEC / ragioni sociali); resilienza
dell'anonimizzazione (retry automatico + "Riprova" per documento); placeholder canonici per lavoro
(coerenti tra documenti con matching normalizzato/fuzzy controllato, abilitano l'export in chiaro);
controllo privacy deterministico su residui noti, candidati PII sconosciuti e placeholder
malformati prima di revisione/export; revisione manuale del testo pseudonimizzato e della mappa;
blocco server-side dell'export pseudonimizzato se il report privacy non è pulito salvo override;
export `.docx` pseudonimizzato senza titolo reale o nomi file identificativi, più versione "in chiaro"
con avviso; revisione guidata pre-export con dashboard fascicolo, checklist UPP, qualità AI,
privacy assistita, red-team e azioni operative sulle lacune; vista comparativa delle fonti per
attore/convenuto/generici con marcatura decisiva/irrilevante/da verificare; editor con autosave,
commenti operativi, cronologia eventi, template di provvedimento e backup/import portabile del
fascicolo; modalità demo civile/penale per formazione e test ripetibili; estrazione richieste robusta
(due chiamate LLM focalizzate + schema vincolante);
fasi asincrone protette da doppio avvio, interrompibili dalla UI e con progresso persistente
(analisi, approfondimento, singola richiesta, ricerca, grafo); analisi parziale possibile solo con conferma esplicita;
editor completo (motivazione "in diritto" + P.Q.M.) con layout mobile più gestibile; anteprima
documenti; ricerca nell'archivio; corpus con upload file, categorie, soglia di rilevanza e permessi
di visibilità/eliminazione; ricerca giuridica con etichette di affidabilità fonte e stato
"ricerca insufficiente" quando non esistono fonti verificabili; grafo con colori robusti, progressi,
scope, annullamento e risultati di ricerca cliccabili; tema chiaro/scuro, upload multiplo drag & drop
e caricamento lazy delle schermate frontend.

## Stato

**M1 + M2 completi**, validati end-to-end (anche su un fascicolo d'appalto reale). Ultima verifica
locale: **116 test backend verdi**, build frontend Vite riuscita, migrazioni allineate, servizi Docker
healthy e `manage.py check` senza issue. Per l'uso operativo passo per passo vedi la
**[Guida operativa](GUIDA.md)**.

---

## Contribuire

Contributi benvenuti — leggi prima **[CONTRIBUTING.md](CONTRIBUTING.md)** (principi non negoziabili
su privacy e §1, setup, test, regole frontend). La **CI** esegue test backend e build frontend a ogni
push e PR. Licenza: **AGPL-3.0-or-later**.
