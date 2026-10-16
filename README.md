# Deribit Price Tracker

Небольшой backend-сервис, который раз в минуту получает публичные индексные
цены `btc_usd` и `eth_usd` с Deribit, сохраняет их в PostgreSQL и предоставляет
REST API для чтения истории.

## Features

- получение `btc_usd` и `eth_usd` через официальный Deribit JSON-RPC HTTP API;
- периодический запуск через Celery Beat каждые 60 секунд;
- хранение цены как `NUMERIC`, времени получения как UNIX timestamp в секундах;
- FastAPI API со строгой валидацией ticker и даты;
- Alembic-миграции, автоматически применяемые при Docker Compose startup;
- unit/API tests без реальных запросов к Deribit;
- Ruff и GitLab CI.

## Stack

Python 3.12, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2.x,
PostgreSQL, Alembic, Celery, Redis, aiohttp, pytest, Docker Compose и Ruff.

## Architecture

Сбор данных:

```text
Celery Beat (60 s)
        ↓
Celery Worker
        ↓
DeribitClient → Deribit public API
        ↓
PriceRepository → PostgreSQL
```

Чтение данных:

```text
FastAPI route → PriceService → PriceRepository → PostgreSQL
```

`DeribitClient` отвечает только за HTTP и проверку ответа Deribit.
`PriceRepository` содержит SQLAlchemy-запросы. `PriceService` содержит сценарии
чтения и перевод календарной даты в UTC-диапазон. Routes занимаются HTTP-
валидацией и формированием ответа. Celery task только координирует получение и
сохранение данных.

## Project structure

```text
app/
  api/              FastAPI dependencies and routes
  clients/          Deribit HTTP client
  core/             settings, logging, ticker enum, Celery setup
  db/               SQLAlchemy model, session factory, repository
  schemas/          response schemas
  services/         read use cases and UTC date conversion
  tasks/            periodic collection task
alembic/             database migrations
tests/               API/repository and Deribit client tests
Dockerfile
docker-compose.yml
```

## Running locally

### Docker (recommended)

Requirements: Docker Engine with Docker Compose v2.

1. Create the environment file:

   ```bash
   cp .env.example .env
   ```

2. Change `POSTGRES_PASSWORD` and update the password inside `DATABASE_URL` in
   `.env`. For the provided URL syntax, use a URL-safe password.

3. Build and start all services:

   ```bash
   docker compose up --build
   ```

The one-shot `migrate` service runs `alembic upgrade head`. API, worker and beat
start only after the migration succeeds. The API is then available at
`http://localhost:8000`; Beat sends the first periodic task after 60 seconds.
If port 8000 is already occupied, set `API_PORT` in `.env` (for example,
`API_PORT=18000`) and use that port in the URLs below.

Useful commands:

```bash
docker compose logs -f api celery-worker celery-beat
docker compose down
docker compose down -v  # also deletes local PostgreSQL and Redis volumes
```

### Without Docker

Run PostgreSQL and Redis separately, set `.env` URLs to their host addresses,
then use four terminals:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
celery -A app.core.celery:celery_app worker --loglevel=INFO
celery -A app.core.celery:celery_app beat --loglevel=INFO
```

When running services directly on the host, set `POSTGRES_HOST=localhost` and
use `localhost` in `DATABASE_URL` and `REDIS_URL`.

## API

All price endpoints require `ticker=btc_usd` or `ticker=eth_usd`. Lists are
ordered newest-first; records with equal timestamps are ordered by newest ID.
Prices are JSON strings so decimal precision is not lost by clients.

### All saved prices

```bash
curl "http://localhost:8000/api/v1/prices?ticker=btc_usd"
```

Returns an empty list when there are no records.

### Latest price

```bash
curl "http://localhost:8000/api/v1/prices/latest?ticker=btc_usd"
```

Returns `404` when the ticker has no records.

### Prices for a UTC date

```bash
curl "http://localhost:8000/api/v1/prices/by-date?ticker=btc_usd&date=2026-10-14"
```

`date` must use `YYYY-MM-DD`. The response contains all records from 00:00:00
inclusive until the next UTC midnight exclusive.

### Health and Swagger

- health: `GET /health`
- Swagger UI: `http://localhost:8000/api/docs`
- OpenAPI schema: `http://localhost:8000/openapi.json`

FastAPI returns its standard `422` response for a missing/unsupported ticker or
an invalid date. Unexpected SQLAlchemy failures are logged and returned as
`503 Database unavailable`.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

API tests exercise the real service and repository through an isolated SQLite
database. Production uses PostgreSQL through `asyncpg`; the Alembic migration
uses PostgreSQL-compatible types. Deribit client tests use fake HTTP sessions,
so the suite never calls the real exchange.

Covered cases include all prices, newest price, empty-result `404`, UTC date
filter, required/unsupported ticker, invalid date, valid Deribit parsing, HTTP
errors and malformed Deribit payloads.

## Lint

```bash
ruff check .
ruff format --check .
```

To apply safe formatting locally:

```bash
ruff check --fix .
ruff format .
```

## Configuration

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy async PostgreSQL URL |
| `REDIS_URL` | Celery broker URL |
| `DERIBIT_BASE_URL` | Deribit API v2 base URL |
| `DERIBIT_TIMEOUT_SECONDS` | Total HTTP timeout |
| `LOG_LEVEL` | Application and worker log level |
| `API_PORT` | Host port mapped to container port 8000 |
| `POSTGRES_*` | PostgreSQL container initialization |

`.env` is ignored by Git. Only non-secret examples live in `.env.example`.

## Design decisions

### PostgreSQL, SQLAlchemy, repository and service

PostgreSQL is required by the assignment and is a good fit for durable,
indexed time-series-like records. SQLAlchemy 2.x provides explicit async
sessions and keeps SQL portable and testable. The repository owns persistence;
the service owns use-case rules such as date boundaries. This is enough
separation for the project without introducing generic repositories or a large
domain layer.

### Decimal / NUMERIC

Financial values must not accumulate binary floating-point artifacts. Python
uses `Decimal`, PostgreSQL uses `NUMERIC(28, 10)`, and API prices serialize as
strings to preserve the exact stored value.

### UNIX timestamp and UTC

`timestamp` is the application's actual receipt time, measured immediately
after a successful Deribit response and stored as integer UNIX seconds. UNIX
time is unambiguous and timezone-independent; all calendar interpretation is
explicitly UTC.

### Date filtering

The phrase “filter by date” is interpreted as `ticker + YYYY-MM-DD` for a full
UTC calendar day. The query uses a half-open interval `[00:00:00, next day
00:00:00)`. This is simpler and less error-prone than constructing a
`23:59:59` boundary, while selecting exactly the same second-resolution data.

### Celery Beat

Beat is the scheduler and sends one collection task every 60 seconds; the
worker executes it. This survives independently of FastAPI request workers and
avoids an unmanaged `while True` loop or duplicate FastAPI background jobs.
Each ticker is handled separately, so one Deribit/DB failure does not prevent
the attempt for the other ticker.

### Redis

Celery needs a broker. Redis is sufficient, familiar and easy to run for this
small test project. No result backend is configured because collection tasks
do not return a result that callers need.

### Docker services

Compose separates `api`, `postgres`, `redis`, `celery-worker` and
`celery-beat`, plus a short-lived `migrate` service. A broker, worker and
scheduler are distinct processes in a correct Celery deployment. Combining
them with the API or database into two containers would make lifecycle,
healthchecks, logs and restarts less reliable. Named volumes retain database
and broker data.

### aiohttp and DeribitClient

The public `GET /public/get_index_price?index_name=...` endpoint needs no API
key. A dedicated async client centralizes URL construction, timeout, connection
lifecycle, network handling and response validation. One `ClientSession` is
reused for both ticker requests in a task and then closed deterministically.

### Database index

The composite `(ticker, timestamp)` index matches all current read paths:
filter by ticker, find the newest timestamp, and filter a ticker by a timestamp
range. No uniqueness constraint is added because two valid collections can
occur in the same second.

### Task failure semantics

The task logs failures per ticker and continues. Partial success is preferable
to losing both data points. There is no retry framework because the next Beat
run arrives in one minute; automatic rapid retries could amplify an exchange
or database outage.

## GitLab CI

`.gitlab-ci.yml` runs Ruff checks and pytest with Python 3.12. After creating an
empty GitLab project, push this repository normally:

```bash
git init
git add .
git commit -m "Implement Deribit price tracker"
git branch -M main
git remote add origin <gitlab-repository-url>
git push -u origin main
```

Repository creation and push require the candidate's GitLab account and are
therefore intentionally not automated by the application.
