# Contribuire a UPPilot

Grazie per l'interesse! UPPilot è un assistente alla redazione di bozze per gli **Uffici per il
Processo**: un dominio delicato, con vincoli forti di **privacy** e una filosofia non negoziabile.
Prima di aprire una PR, leggi questa pagina.

## Principi non negoziabili

Ogni contributo deve rispettarli — una PR che li viola non sarà accettata, per quanto buono sia il codice.

1. **§1 — Niente conclusioni giuridiche definitive.** Il sistema scrive ciò che è *oggettivo*; ciò
   che richiede discernimento va posto all'operatore come **quesito** ("[DA DECIDERE]"), mai come
   decisione. Non aggiungere funzioni che "decidono" al posto del giudice.
2. **Privacy by design.** Nessun documento può raggiungere un LLM senza essere passato dal **Privacy
   Filter** (pseudonimizzazione). Non bypassare il vincolo `utilizzabile` sui documenti. L'uso di LLM
   commerciali resta **opt-in esplicito**; la query di ricerca esce sempre pseudonimizzata.
3. **Local-first.** Il default è il modello locale. Niente dipendenze che forzino il cloud.
4. **Niente dati reali nel repo.** Mai committare fascicoli, pesi dei modelli, `.env`, segreti o dati
   personali. Per i test usa dati **fittizi** generati al volo.

## Setup ambiente di sviluppo

Requisiti: Docker + Docker Compose. Su Mac, Ollama sull'host (vedi [README](README.md)).

```bash
cp .env.example .env
make provision          # scarica i pesi dei modelli (non versionati)
make up-mac             # oppure: make up-gpu (Linux/NVIDIA)
```

Servizi: frontend `:5173`, backend `:8000`, privacy-filter `:8001`.

## Eseguire i test

La suite backend gira nel container e usa Postgres + pgvector (è **ermetica**: nessuna chiamata di
rete reale agli LLM):

```bash
docker compose exec backend pytest --ds=config.settings.test -q
```

Il frontend si verifica con typecheck + build:

```bash
docker compose exec frontend npx tsc --noEmit
docker compose exec frontend npx vite build
```

La **CI** (GitHub Actions, `.github/workflows/ci.yml`) esegue entrambe a ogni push e PR: la tua PR
deve essere verde.

## Regole per il frontend (vincolanti)

La UI usa **esclusivamente** componenti **shadcn/ui** + Tailwind. Niente componenti custom, niente
CSS a mano, niente valori "magici". Le regole complete sono in **[`frontend/CLAUDE.md`](frontend/CLAUDE.md)**:
leggile prima di toccare la UI. In sintesi: se manca un componente, aggiungilo con
`npx shadcn@latest add <nome>`; i quesiti devono restare visivamente distinti; l'avviso GDPR è
persistente, mai un toast effimero.

## Stile del codice

- **Backend**: Python, l'app Django parla con gli LLM **solo** tramite le astrazioni in `backend/ai/`
  (`OCRBackend`, `LLMBackend`, `AnonymizationService`, `LegalSearchProvider`). Non importare librerie
  ML in-process nell'app. Aggiungi test per ogni nuovo comportamento.
- **Italiano** per testi UI, commenti di dominio e messaggi all'utente; termini tecnici/identificatori
  restano in lingua originale.
- **Migrazioni**: includi sempre le migrazioni Django generate dai cambi di modello.

## Commit e Pull Request

- Commit piccoli e descrittivi (in italiano va benissimo); prefisso tipo `feat:` / `fix:` / `docs:` /
  `chore:` gradito.
- Apri la PR verso `main` con una descrizione di **cosa** cambia e **perché**, e conferma che:
  - [ ] i test backend passano (`pytest`);
  - [ ] frontend: `tsc` e `build` puliti (se hai toccato la UI);
  - [ ] nessun dato reale / segreto / peso modello aggiunto;
  - [ ] rispettati §1 e i vincoli privacy.

## Licenza

Contribuendo accetti che il tuo contributo sia rilasciato sotto **AGPL-3.0-or-later**, come il resto
del progetto.
