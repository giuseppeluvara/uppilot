# Prompt iniziale per Claude Code — Piattaforma di assistenza alla redazione di bozze per l'UPP

> **Nome di lavoro:** `Assistente Bozze UPP` (placeholder, da definire)
> **Natura:** progetto open source, interamente dockerizzato, local-first, per supportare gli Uffici per il Processo (UPP) del Ministero della Giustizia nella redazione di **bozze di sentenza/parere** che resteranno comunque soggette a revisione umana esterna alla piattaforma.

---

## 0. Come usare questo documento

Questo è il prompt iniziale di bootstrap. Descrive **la visione completa** del progetto e definisce con precisione **cosa costruire nel primo milestone (M1)**. Tutto ciò che è marcato come M2/M3 va tenuto presente nell'architettura (interfacce, modello dati, separazione dei servizi) ma **non implementato ora**: l'obiettivo immediato è una fetta verticale funzionante.

Prima di scrivere codice: proponi una struttura di repository e un piano di implementazione di M1 in step verificabili, poi procedi.

---

## 1. Visione e filosofia di prodotto

La piattaforma assiste un **singolo operatore UPP** (il *redattore*) nella stesura della bozza. **Non** sostituisce il giudizio umano e **non** gestisce la fase di revisione del magistrato (che avviene fuori dalla piattaforma).

Principio guida, non negoziabile, da riflettere in ogni scelta di UX e di prompt verso gli LLM:

- **Tutto ciò che è oggettivo, lo scrive il sistema** — riassunto del fatto, elenco delle domande delle parti, mappatura degli allegati, rilievo delle non contestazioni, individuazione di chi grava l'onere probatorio.
- **Tutto ciò che richiede discernimento giuridico, il sistema lo pone come interrogativo strutturato all'umano** — es. *"L'onere della prova su questo punto sembra spettare a X: confermi?"*, *"La domanda n. 2 risulta provata dall'all. 4? Verifica."* — **mai** una conclusione spacciata per definitiva.

In una frase: **un sintetizzatore, un organizzatore di flusso e un consigliere — non un tool che fa il lavoro al posto dell'operatore.**

---

## 2. Il flusso di lavoro dell'UPP da modellare

Il processo di analisi reale di un UPP esperto, che la piattaforma deve accompagnare:

1. Lettura del fascicolo e di tutti gli atti delle parti.
2. Comprensione di cosa chiedono le parti.
3. Stesura della **bozza "in fatto"**.
4. Analisi **per singola richiesta/domanda**, in ordine:
   - cosa vuole la parte;
   - ricerca per capire se la pretesa è fondata;
   - analisi dei documenti e dei due fascicoli;
   - individuazione di **a chi spetta l'onere probatorio**;
   - verifica di allegati/istruttoria per capire se i fatti sono provati;
   - rilievo delle **non contestazioni**;
   - formulazione di una valutazione (che, secondo il principio §1, resta un interrogativo dove discrezionale).

Stati del lavoro (state machine): `bozza in corso` → `analizzato` → `bozza generata` → `in revisione (interna all'utente)` → `completato`. (La revisione del magistrato è fuori scope.)

---

## 3. Architettura

**Monolite Django modulare** (un solo codebase applicativo) **+ servizi AI containerizzati separati**, con cui Django comunica esclusivamente via HTTP. Nessuna libreria ML importata in-process nell'app Django: questo evita il dependency hell tra stack ML incompatibili e disaccoppia sviluppo e deployment.

```
┌────────────────────────────────────────────────────────┐
│  docker-compose (installabile in locale su Win/Lin/mac) │
│                                                          │
│  ┌─────────────┐   HTTP   ┌──────────────────────────┐  │
│  │ React SPA   │ <──────> │ Django + DRF (monolite)  │  │
│  │ (frontend)  │   REST   │  - app: casi/documenti   │  │
│  └─────────────┘          │  - app: analisi/bozze    │  │
│                           │  - app: storico          │  │
│                           │  - astrazioni backend AI │  │
│                           └──────────┬───────────────┘  │
│                                      │ HTTP              │
│         ┌────────────────┬───────────┼──────────────┐   │
│         ▼                ▼           ▼              ▼   │
│  ┌────────────┐  ┌──────────────┐ ┌──────────┐ ┌──────┐ │
│  │ Ollama     │  │ Privacy      │ │ Postgres │ │ task │ │
│  │ (LLM       │  │ Filter       │ │ +pgvector│ │ queue│ │
│  │  locale +  │  │ (OpenAI,     │ └──────────┘ └──────┘ │
│  │  GLM-OCR)  │  │  locale)     │                       │
│  └────────────┘  └──────────────┘                       │
│         ▲                                                │
│         │ (opzionale, opt-in) LLM commerciale via API    │
└────────────────────────────────────────────────────────┘
```

### Componenti

- **Frontend:** React SPA che consuma le API Django REST. La fase di lavoro/revisione è molto interattiva (editing inline, evidenziazioni, gestione per-richiesta), quindi l'SPA è giustificata rispetto a soluzioni server-rendered.
- **Backend:** Django + Django REST Framework. Monolite ma organizzato in app distinte e con interfacce nette verso i servizi AI.
- **Task queue** (es. Celery o RQ + Redis): OCR e generazione sono operazioni lunghe → asincrone, con stato/progresso esposto al frontend (idealmente streaming dei risultati).
- **Database:** Postgres con estensione **pgvector** (non usata in M1, ma installata e pronta per il RAG futuro).
- **Servizi AI containerizzati:**
  - **Ollama** — espone `http://ollama:11434`. Ospita sia il modello **GLM-OCR** (`glm-ocr`, modello *vision*, 0.9B param) sia gli **LLM locali** (modelli scaricabili via Ollama).
  - **OpenAI Privacy Filter** — servizio separato (gira con torch/transformers, **non** via Ollama; modello da Hugging Face `openai/privacy-filter`, Apache 2.0). Espone un endpoint interno di pseudonimizzazione.
- **Provider LLM commerciali:** opzionali, opt-in (vedi §5). Accessibili dietro l'astrazione `LLMBackend`.

### Astrazioni da definire nel codice (interfacce/Protocol)

Il resto della piattaforma deve parlare **solo** con queste interfacce, mai direttamente con Ollama o con una libreria specifica. Questo protegge da abbandono upstream e da lock-in.

- `OCRBackend` → implementazione `GlmOcrBackend` (via Ollama).
- `LLMBackend` → implementazioni `OllamaLLMBackend` (locale, default) e `CommercialLLMBackend` (es. OpenAI/Anthropic/Gemini/Mistral, opt-in).
- `AnonymizationService` → implementazione `OpenAIPrivacyFilterService`.
- `LegalSearchProvider` → implementazione M2 (vedi §6); in M1 può essere uno stub.

---

## 4. Ingestione documenti

- L'utente carica **file sciolti** in **tre sezioni** distinte:
  1. **Documenti generici** (utili al contesto)
  2. **Fascicolo dell'attore**
  3. **Fascicolo del convenuto/ricorrente**
- Tipi attesi: prevalentemente **PDF nativi digitali** (testo selezionabile, tipici del PCT), ma anche **scansioni**, **immagini** e **manoscritti**.
- Estrazione testo:
  - PDF nativo → estrazione diretta del testo (es. PyMuPDF); **niente OCR** se il testo è già selezionabile.
  - Scansione / immagine / manoscritto → rasterizzazione pagina→immagine (PyMuPDF/pdf2image) poi **GLM-OCR**.
- **GLM-OCR** prende in input **immagini** e ha modalità distinte da specificare nel prompt: `Text Recognition:`, `Table Recognition:`, `Figure Recognition:`.
- **Segnalazione di mala lettura:** il sistema deve fare un lavoro certosino e **avvisare esplicitamente** quando la confidenza dell'OCR è bassa o il testo è dubbio (es. manoscritti), marcando i passaggi incerti perché l'utente li verifichi. Mai presentare testo OCR dubbio come affidabile.

---

## 5. Privacy / GDPR (vincolo fondamentale)

Il contesto è giudiziario e i dati sono particolarmente sensibili. Regole tassative:

- **Ogni documento caricato passa OBBLIGATORIAMENTE dal Privacy Filter** prima di poter essere usato/inviato a qualunque LLM. Il filtro produce una versione **pseudonimizzata** + una mappa delle entità mascherate.
- Al caricamento, per ciascun file, l'utente sceglie:
  - **consultare/verificare** l'anonimizzazione (rivedere cosa è stato mascherato), oppure
  - **accettare direttamente** senza verifica — il **singolo file** o **tutti i file in blocco**.
- È l'**utente** a decidere se inviare o meno il materiale (verificato o accettato così com'è). Solo il materiale "accettato" entra nelle fasi successive.
- **Avviso chiaro e persistente nella UI:** il Privacy Filter esegue **pseudonimizzazione, non anonimizzazione**; sotto il GDPR il dato pseudonimizzato **resta dato personale**. Non è una garanzia di conformità.
- **Default in produzione su fascicoli reali: LLM locale.** L'uso di LLM **commerciali** in cloud è possibile solo come **opt-in esplicito**, sempre sul testo pseudonimizzato, e con warning inequivocabile sui limiti di cui sopra.

---

## 6. Ricerca giuridica — modalità "spunti di approfondimento" (M2, da architettare ora)

La ricerca **non** è integrazione autoritativa di banche dati (le banche dati italiane serie sono a pagamento/login o ad accesso ristretto). È un **assistente di approfondimento** in linea con la filosofia §1:

- propone spunti del tipo: *"Il contesto suggerisce di cercare giurisprudenza in merito a… La ricerca web ha prodotto risultati in termini di… Suggerisco di integrare giurisprudenza da…"*;
- la **query di ricerca esce sempre pseudonimizzata** (mai nomi/dati delle parti verso l'esterno);
- l'output sono suggerimenti che l'utente valuta e integra a sua discrezione, non citazioni date per buone.

In M1: definire l'interfaccia `LegalSearchProvider` e lasciare uno stub. In M2: implementazione con web search generica + opzione "incolla manualmente i risultati".

---

## 7. Output

- **Editor interattivo** nel browser per costruire/modificare la bozza.
- **Export Word (.docx)** scaricabile (implementazione piena in M2; in M1 prevedere il punto di estensione).
- La struttura del parere/sentenza segue **sample di output** che verranno forniti dall'utente in un'apposita sezione/cartella di progetto (intestazione, "in fatto", motivazione per ciascuna domanda, P.Q.M., ecc.). Il codice deve poter caricare questi sample come guida/template per i prompt di generazione.

---

## 8. UI/UX

Interfaccia **essenziale, minimale, pulita**: spazi chiari, pochissimi input esterni, solo ciò che serve per lavorare. Italiano. Niente fronzoli. Tre aree principali: caricamento/sezioni documenti, area di analisi e stesura per-richiesta, archivio/storico.

---

## 9. Login e storicizzazione

- **Autenticazione** con login (singolo utente redattore; il modello dati non deve precludere ruoli futuri, ma M1 = un utente).
- **Storicizzazione di tutti i lavori**: ogni caso/lavoro è salvato e ritrovabile.
- Sezione **Archivio/Storico** per rivedere i lavori precedenti.

---

## 10. Modello dati (bozza, da raffinare)

- `Utente`
- `Lavoro` (il caso/fascicolo di lavoro) — stato, timestamp, riferimento utente.
- `SezioneDocumenti` (tipo: generici | attore | convenuto)
- `Documento` — file originale, tipo, testo estratto, esito OCR + flag di confidenza, **testo pseudonimizzato**, mappa entità mascherate, stato di accettazione (verificato / accettato senza verifica).
- `Richiesta` (domanda di una parte) — testo, parte richiedente, stato, esiti di analisi (onere probatorio individuato, allegati collegati, non contestazioni rilevate), e i **quesiti aperti** posti all'utente.
- `Bozza` — sezione "in fatto" + contenuto per-richiesta, versione editabile.

---

## 11. Stack tecnico (riepilogo)

Python / Django / Django REST Framework · React (SPA) · Postgres + pgvector · Redis + Celery/RQ · Docker + docker-compose (cross-platform: Windows/Linux/macOS) · Ollama (GLM-OCR + LLM locali) · OpenAI Privacy Filter (locale) · PyMuPDF/pdf2image per rasterizzazione.

---

## 12. Scope di M1 (la fetta verticale da costruire ORA)

1. Setup repository + `docker-compose` con tutti i servizi (Django, React, Postgres, Redis, Ollama, Privacy Filter) che si avviano insieme in locale.
2. Login e modello dati base con storicizzazione dei `Lavoro`.
3. Creazione di un nuovo lavoro e upload file nelle 3 sezioni.
4. Estrazione testo: PDF nativo (diretta) + GLM-OCR (scansioni/immagini/manoscritti) con **flag di bassa confidenza**.
5. **Privacy Filter obbligatorio** su ogni file, con flusso di scelta utente (verifica / accetta singolo / accetta tutti) e warning GDPR.
6. Analisi LLM (locale di default): sintesi del **fatto** + estrazione strutturata delle **richieste** delle parti, ciascuna con stato.
7. Generazione bozza **"in fatto"** + elenco strutturato delle richieste, applicando il principio §1 (oggettivo → testo; discrezionale → quesito).
8. Editor interattivo minimale per rivedere/modificare la bozza.
9. Sezione **Storico** per rivedere i lavori.

**Fuori da M1 (ma architettati):** ragionamento "in diritto" completo per richiesta · ricerca giuridica "spunti di approfondimento" (§6) · export .docx pieno (§7) · RAG su corpus (pgvector) · LLM commerciali (interfaccia pronta, attivazione opt-in).

---

## 13. Decisioni aperte / convenzioni

- **Licenza del progetto:** `TBD` (raccomandazione: AGPL-3.0 per un progetto pubblico anti-appropriazione; da confermare).
- Verificare **alla fonte** la licenza dei pesi di GLM-OCR (famiglia GLM/Z.ai) prima di distribuire qualunque riferimento ai modelli.
- I pesi dei modelli **non vanno in git**: scaricati al setup via script di provisioning; nel repo solo nome modello + versione/hash.
- Commit/PR atomici, test su backend e logica di estrazione/anonimizzazione, README con istruzioni di avvio one-command.

---

### Istruzione operativa finale per Claude Code

Parti proponendo (a) la struttura del repository, (b) il `docker-compose` con i servizi, (c) il modello dati Django, (d) le interfacce `OCRBackend` / `LLMBackend` / `AnonymizationService` / `LegalSearchProvider`. Poi implementa M1 per step verificabili, fermandoti a far validare ciascun blocco.
