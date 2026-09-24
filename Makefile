# Все команды идут через podman: на машине разработчика ничего не устанавливается.
PODMAN ?= podman
COMPOSE ?= podman compose -f docker/compose.yaml
IMAGE ?= localhost/deckforge:dev
RUN = $(PODMAN) run --rm -v $(CURDIR):/app:z -w /app -e PYTHONPATH=/app/src $(IMAGE)

.PHONY: help image test lint typecheck gates schemas checks up down logs shell clean warm-cache

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

image: ## Собрать образ приложения
	$(PODMAN) build -f docker/Dockerfile -t $(IMAGE) .

worker-image: ## Собрать образ воркера (приложение + LibreOffice); гейт кириллицы внутри
	$(PODMAN) build -f docker/Dockerfile.worker -t localhost/deckforge:worker .

preview-test: worker-image ## Тесты рендера превью (нужен LibreOffice)
	$(PODMAN) run --rm -v $(CURDIR):/app:z -w /app -e PYTHONPATH=/app/src \
		localhost/deckforge:worker pytest -q -m needs_libreoffice

test: ## Тесты
	$(RUN) pytest -q

lint: ## ruff
	$(RUN) ruff check src tests scripts

format: ## ruff format
	$(RUN) ruff format src tests scripts

typecheck: ## mypy
	$(RUN) mypy

schemas: ## Перегенерировать JSON-схемы из доменных моделей
	$(RUN) python scripts/gen_schemas.py

warm-cache: ## Предразбор шаблонов кейса в кэш манифестов (D1). TEMPLATES=путь/*.pptx
	$(RUN) python scripts/warm_template_cache.py $(TEMPLATES)

gates: ## CI-гейты: C1/C2 (лицензии), C6 (константы шаблона), контракты скиллов
	$(RUN) python scripts/check_licenses.py
	$(RUN) python scripts/lint_no_template_constants.py
	$(RUN) python scripts/lint_skill_contracts.py

checks: ## Показать реестр проверок аудита
	$(RUN) python -m deckforge.cli checks --list

up: ## Поднять сервисы
	$(COMPOSE) up -d --build

down: ## Остановить сервисы
	$(COMPOSE) down

logs: ## Логи
	$(COMPOSE) logs -f --tail=100

shell: ## Оболочка в образе
	$(PODMAN) run --rm -it -v $(CURDIR):/app:z -w /app -e PYTHONPATH=/app/src $(IMAGE) bash

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
