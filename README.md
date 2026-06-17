# UPPilot

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
  come **opt-in esplicito**, sempre su testo pseudonimizzato.

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
ollama serve                    # in un terminale a parte
make up-mac

# Linux/server con GPU NVIDIA:
make up-gpu
```

Servizi esposti in dev: frontend `:5173`, backend API `:8000`, privacy-filter `:8001`.

---

## Architettura (sintesi)

Monolite **Django + DRF** che comunica con i servizi AI **solo via HTTP**, dietro astrazioni
(`OCRBackend`, `LLMBackend`, `AnonymizationService`, `LegalSearchProvider`). Nessuna libreria ML
importata in-process nell'app Django.

```
React SPA ──REST──> Django + DRF ──HTTP──> Ollama (GLM-OCR + LLM locali)
                          │      ──HTTP──> Privacy Filter (openai/privacy-filter)
                          ├──> Postgres + pgvector   (pgvector pronto, non usato in M1)
                          └──> Redis + Celery (OCR/generazione asincroni)
```

Dettaglio di scope e milestone: vedi `PROMPT_INIZIALE_assistente_bozze_upp.md`.

## Stato

**M1 — fondamenta** in costruzione: scaffolding, `docker-compose`, modello dati, interfacce AI.
