COMPOSE      = docker compose
MAC          = -f docker-compose.yml -f docker-compose.mac.yml
OLLAMA       = -f docker-compose.yml -f docker-compose.ollama.yml
GPU          = -f docker-compose.yml -f docker-compose.ollama.yml -f docker-compose.gpu.yml

.PHONY: help license provision up up-mac up-ollama up-gpu down logs migrate makemigrations test sh

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

license: ## Scarica il testo canonico AGPL-3.0 in LICENSE
	curl -sSL https://www.gnu.org/licenses/agpl-3.0.txt -o LICENSE

provision: ## Scarica i pesi dei modelli (Ollama + privacy-filter)
	./scripts/provision_models.sh

up: ## Avvio base (OLLAMA_BASE_URL da .env)
	$(COMPOSE) up --build

up-mac: ## Avvio su Mac (Ollama sull'host)
	$(COMPOSE) $(MAC) up --build

up-ollama: ## Avvio con Ollama in container (Linux, CPU)
	$(COMPOSE) $(OLLAMA) up --build

up-gpu: ## Avvio con Ollama in container + GPU NVIDIA
	$(COMPOSE) $(GPU) up --build

down: ## Ferma e rimuove i container
	$(COMPOSE) down

logs: ## Tail dei log
	$(COMPOSE) logs -f

migrate: ## Applica le migrazioni
	$(COMPOSE) exec backend python manage.py migrate

makemigrations: ## Genera le migrazioni
	$(COMPOSE) exec backend python manage.py makemigrations

test: ## Esegue i test backend
	$(COMPOSE) exec backend pytest

sh: ## Shell nel container backend
	$(COMPOSE) exec backend sh
