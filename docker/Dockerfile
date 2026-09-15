# Образ приложения: парсинг, композиция, вёрстка, аудит, API.
# Инференс сюда не тащим — он отдельным сервисом (группа зависимостей `inference`).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=2.3.0 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libcairo2 libpango-1.0-0 libgdk-pixbuf-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==${POETRY_VERSION}"

WORKDIR /app
COPY pyproject.toml poetry.lock* ./
RUN poetry install --with dev,ui --no-root --no-interaction

COPY src/ src/
COPY configs/ configs/
COPY prompts/ prompts/
COPY skills/ skills/
COPY schemas/ schemas/
COPY scripts/ scripts/
COPY assets/ assets/
COPY tests/ tests/
RUN poetry install --only-root --no-interaction

ENV PYTHONPATH=/app/src
CMD ["deckforge", "--help"]
