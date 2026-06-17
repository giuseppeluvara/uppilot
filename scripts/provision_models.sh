#!/usr/bin/env bash
# Scarica i pesi dei modelli usati da UPPilot.
# I PESI NON stanno in git (§200): questo script li recupera al setup.
set -euo pipefail

# Carica le variabili da .env se presente
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
OCR_MODEL="${OCR_MODEL:-glm-ocr:latest}"
LLM_MODEL="${LLM_MODEL:-qwen2.5:7b-instruct-q4_K_M}"
PRIVACY_FILTER_MODEL="${PRIVACY_FILTER_MODEL:-openai/privacy-filter}"

echo "==> Ollama: $OLLAMA_BASE_URL"

pull_ollama() {
  local model="$1"
  echo "==> Pull modello Ollama: $model"
  curl -fsSL "$OLLAMA_BASE_URL/api/pull" -d "{\"model\": \"$model\"}" >/dev/null
}

# GLM-OCR (vision) e LLM locale
pull_ollama "$OCR_MODEL"
pull_ollama "$LLM_MODEL"

# Privacy Filter (HuggingFace). ATTENZIONE: usare il repo UFFICIALE openai/privacy-filter
# (esiste un repo fake). Lo scarico in cache HF; il container privacy-filter lo monta.
echo "==> Pre-fetch privacy-filter: $PRIVACY_FILTER_MODEL"
if command -v huggingface-cli >/dev/null 2>&1; then
  huggingface-cli download "$PRIVACY_FILTER_MODEL" --quiet || \
    echo "    (skip) download fallito: verrà scaricato al primo avvio del servizio."
else
  echo "    huggingface-cli non installato: il modello verrà scaricato al primo avvio del servizio."
fi

echo "==> Provisioning completato."
