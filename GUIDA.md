# UPPilot — Guida operativa

Guida pratica per l'**operatore** (redattore UPP). Per i dettagli tecnici/architetturali vedi
[`README.md`](README.md).

---

## ⚠️ Da tenere sempre presente (privacy)

- UPPilot **non sostituisce il tuo giudizio**: ciò che è oggettivo lo scrive il sistema, ciò che è
  discrezionale ti viene posto come **domanda** ("[DA DECIDERE]"). La motivazione "in diritto" e il
  P.Q.M. li scrivi **tu**.
- Il filtro privacy esegue **pseudonimizzazione, non anonimizzazione**: ai fini del GDPR il dato
  resta dato personale. **Non è una garanzia di conformità.**
- L'uso di un LLM commerciale in cloud è **opt-in** e va attivato consapevolmente: invia testo
  (pseudonimizzato) a un servizio esterno.
- La bozza prodotta resta **soggetta a revisione umana** fuori dalla piattaforma.

---

## 1. Aprire il programma

UPPilot si **avvia da solo** quando accendi il PC. Apri il browser su:

> **http://localhost:5173**

ed entra con le tue credenziali.

Da un altro dispositivo sulla stessa rete Wi-Fi/LAN puoi aprire:

> **http://mac-mini.local:5173**

In alternativa usa l'IP statico del Mac mini:

> **http://192.168.1.62:5173**

Se la pagina non si apre, attendi ~1 minuto (i servizi stanno partendo) e ricarica. Se ancora non
va, vedi [Problemi comuni](#6-problemi-comuni).

---

## 2. Il flusso di lavoro, passo per passo

### a) Crea un nuovo lavoro
Nella schermata **Lavori**, scrivi un titolo (es. "Rossi c. Bianchi") e premi **Nuovo lavoro**.
Per riaprire un lavoro esistente, **clicca sulla sua riga** nell'archivio (puoi cercarlo con il
campo di ricerca, scorciatoia `/`).

### b) Carica i documenti
Dentro il lavoro ci sono tre sezioni: **Documenti generici**, **Fascicolo dell'attore**,
**Fascicolo del convenuto/ricorrente**.
- Trascina i file nell'area della sezione giusta (oppure clicca "Scegli i file"). Puoi caricarne
  **più alla volta**.
- Sono accettati PDF (anche scansioni) e immagini/manoscritti (`png`, `jpg`, `tiff`, `bmp`, `webp`).
  Il limite predefinito è **50 MB per file**, salvo diversa configurazione dell'installazione.
- L'icona 👁 apre l'**anteprima** del documento.

### c) Estrazione e anonimizzazione (automatiche)
Ogni documento viene letto (testo o OCR) e poi **pseudonimizzato**. Vedrai gli stati avanzare da
soli. Se l'anonimizzazione fallisce, compare **"Anonimizzazione fallita"** con il pulsante
**Riprova**.

### d) Verifica e accetta i documenti
Per ogni documento pseudonimizzato puoi:
- **Rivedi anonimizzazione** → vedi e puoi correggere il testo mascherato e la mappa delle entità;
- **Salva correzioni** se noti un residuo o una mappatura errata, poi conferma di nuovo;
- **Confermo, verificato** oppure **Accetta senza verifica** (o **Accetta tutti**).

> Solo i documenti **accettati** entrano nelle fasi successive.

### e) Analisi (in fatto + richieste)
Premi **Avvia analisi**. Se il pulsante non è attivo, il riquadro sopra l'analisi indica cosa manca
(di solito almeno un documento accettato). Il sistema produce:
- la **bozza "in fatto"** (modificabile);
- l'elenco delle **richieste delle parti**, classificate per tipo (domanda, difesa/eccezione,
  riconvenzionale, istruttoria), con confidenza, avvisi di coerenza, onere probatorio, non
  contestazioni filtrate, allegati pertinenti e **quesiti** da decidere.

Se hai avviato l'analisi per errore o vuoi modificare prima i documenti, premi **Interrompi** mentre
la fase è in corso.

### f) Approfondimento "in diritto"
Premi **Approfondisci in diritto**. Per ogni richiesta avrai lo scaffold oggettivo; tu scrivi la
**Motivazione (in diritto)** nel riquadro dedicato e premi **Salva motivazione**. Anche questa fase
può essere interrotta con **Interrompi** mentre è in corso.

### g) Spunti di ricerca (facoltativo)
Nella sezione spunti puoi **Cercare sul web** o **Incollare risultati** trovati altrove: il
sistema ne ricava suggerimenti (non citazioni definitive). La query esce sempre pseudonimizzata.
Se la ricerca web non restituisce fonti verificabili, lo spunto viene marcato come
**Ricerca insufficiente**: riformula la query o incolla risultati manuali. La ricerca in corso può
essere fermata con **Interrompi**.

### h) P.Q.M. ed esportazione
- Compila il **P.Q.M.** nel riquadro in fondo.
- Esporta in Word:
  - **Scarica Word** → bozza **pseudonimizzata** (placeholder al posto dei dati);
  - **In chiaro** ⚠️ → bozza con i **dati reali** delle parti (de-pseudonimizzata) — da trattare
    con cautela.
Se il controllo privacy segnala residui, l'export pseudonimizzato chiede un override esplicito:
meglio rientrare in **Rivedi anonimizzazione** e correggere prima.

### i) Corpus di riferimento (facoltativo, migliora l'analisi)
Dalla voce **Corpus** puoi caricare normativa/giurisprudenza (testo manuale o file `pdf`, `txt`,
`md`, con categoria). Una volta indicizzata, l'analisi "in diritto" vi attinge automaticamente, e
puoi farci ricerche semantiche. I documenti che carichi nel corpus sono visibili a te; il materiale
globale/condiviso è gestito dagli amministratori.

---

## 3. LLM locale vs commerciale

Di default tutte le elaborazioni usano il **modello locale** (nessun dato esce dal PC). Dentro un
lavoro puoi spuntare **"Usa un LLM commerciale in cloud"** per usare un modello più potente: appare
un **avviso** perché il testo (pseudonimizzato) viene inviato a un servizio esterno. Non è attivabile
globalmente per errore: va scelto esplicitamente dalla schermata del lavoro. Richiede una chiave API
configurata (vedi README, sezione `.env`).

---

## 4. Spegnere / chiudere

- **Puoi semplicemente chiudere il PC**: alla riaccensione UPPilot riparte da solo.
- Per **fermare** volontariamente i servizi (dalla cartella del progetto, nel Terminale):
  ```bash
  make down
  ```
  Per riavviarli a mano:
  ```bash
  make up-mac      # Mac (Ollama sull'host)
  ```

---

## 5. Backup e ripristino dei dati

I dati vivono in due posti: il **database** (lavori, analisi, bozze) e i **file caricati**.
Esegui questi comandi dalla cartella del progetto.

**Backup database:**
```bash
docker compose exec -T db pg_dump -U uppilot uppilot > backup_uppilot.sql
```

**Backup dei documenti caricati:**
```bash
docker compose cp backend:/app/media ./backup-media
```

**Ripristino database** (su un'installazione pulita, dopo `make up-mac`):
```bash
cat backup_uppilot.sql | docker compose exec -T db psql -U uppilot uppilot
```

> Conserva i backup in un luogo sicuro: contengono **dati personali**.

---

## 6. Problemi comuni

| Sintomo | Cosa fare |
|---|---|
| La pagina `:5173` non si apre | Attendi 1 minuto e ricarica. Verifica che **Docker Desktop** sia avviato (icona nella barra in alto). |
| Da iPad/altro dispositivo non si apre `mac-mini.local:5173` | Prova `http://192.168.1.62:5173`. Verifica che il dispositivo sia sulla stessa rete del Mac mini. |
| Compare "Ambiente locale da verificare" | Leggi il dettaglio nel banner: indica se mancano Redis, privacy-filter, Ollama o un modello locale. |
| L'analisi resta "in corso" o va in errore | Se devi fermarla subito premi **Interrompi**. Se il problema si ripete, serve **Ollama** attivo sull'host e visibile ai container: avvia con `OLLAMA_HOST=0.0.0.0:11434 ollama serve`; se manca un modello, rilancia `make provision`. |
| "Anonimizzazione fallita" su un documento | Premi **Riprova**. Su PC senza GPU il filtro è più lento: riprova a documento. |
| L'opzione LLM commerciale dà errore | Manca la **chiave API**: impostala in `.env` (`COMMERCIAL_LLM_API_KEY`) e riavvia (`make up-mac`). |
| Voglio ripartire da zero | `make down` poi `make up-mac`. (Per cancellare anche i dati: `docker compose down -v` — **attenzione, elimina tutto**.) |

---

## 7. Limiti da conoscere

- La pseudonimizzazione è efficace ma **non perfetta**: rivedi sempre l'anonimizzazione sui dati
  sensibili prima di accettare.
- L'OCR su manoscritti/scansioni di bassa qualità può sbagliare: i passaggi dubbi sono segnalati
  con **"bassa confidenza"** — verificali.
- I suggerimenti di ricerca e le proposte del sistema sono **spunti da valutare**, mai conclusioni
  definitive.
