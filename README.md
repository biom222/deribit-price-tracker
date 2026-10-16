# Deribit Price Tracker

A small backend that polls Deribit for `btc_usd` and `eth_usd` index prices
every minute, stores them in PostgreSQL and exposes a read-only REST API.

## Features

- `btc_usd` and `eth_usd` from the public Deribit JSON-RPC HTTP API;
- Celery Beat polling every 60 seconds;
- `NUMERIC` prices and UNIX receipt timestamps in seconds;
- FastAPI with ticker and calendar date validation;
- Alembic migrations applied automatically on Docker Compose startup;
- unit/API tests без реальных запросов к Deribit;
- Ruff and GitLab CI.

## Stack

Python 3.12, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2.x,
PostgreSQL, Alembic, Celery, Redis, aiohttp, pytest, Docker Compose и Ruff.

## Architecture

Collection:

```text
Celery Beat (60 s)
        ↓
Celery Worker
        ↓
DeribitClient → Deribit public API
        ↓
PriceRepository → PostgreSQL
```

Reading:

```text
FastAPI route → PriceService → PriceRepository → PostgreSQL
```

`DeribitClient` owns HTTP and Deribit response validation. `PriceRepository`
owns SQLAlchemy queries. `PriceService` handles reads and UTC date boundaries.
Routes handle HTTP validation and responses. The Celery task coordinates
fetching and saving prices.

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

Run PostgreSQL and Redis separately. Celery workers are supported on Linux;
on Windows use Docker Compose or WSL2, not a native Windows worker.
Prepare the environment once:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env
```

Then edit `DATABASE_URL` and `REDIS_URL` in `.env`: use the actual host, port,
database and credentials of your running PostgreSQL and Redis. The example
hostnames `postgres` and `redis` work only inside the Compose network.
`POSTGRES_*` initializes the Compose database; the Python application reads
only `DATABASE_URL` for its database connection.

Apply migrations, then run each process in a separate terminal with the same
virtual environment activated (three terminals total):

```bash
alembic upgrade head
uvicorn app.main:app --reload
celery -A app.core.celery:celery_app worker --concurrency=1 --loglevel=INFO
celery -A app.core.celery:celery_app beat --loglevel=INFO
```

### Deployment notes

Use one Beat instance and one collection worker with `--concurrency=1` and
prefetch `1`, as configured in Compose. This serializes collection runs;
additional collection workers would require a shared lock to prevent overlap.
API processes can be scaled independently.

Set real database credentials before deployment and keep `.env` outside Git.
The provided Compose configuration exposes only the API port, not PostgreSQL
or Redis. For internet-facing deployment, put the API behind a TLS reverse
proxy and restrict network access as needed; authentication is outside this
assignment's scope. `/health` checks process liveness, not database readiness.
For an updated schema, rerun `docker compose run --rm migrate` before restarting
application services; back up PostgreSQL before applying production migrations.

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

`date` accepts only a valid `YYYY-MM-DD` calendar date, not a UNIX timestamp or
datetime. The response contains all records from 00:00:00
inclusive until the next UTC midnight exclusive.

### Health and Swagger

- liveness: `GET /health` (technical endpoint; no ticker needed)
- Swagger UI: `http://localhost:8000/api/docs`
- OpenAPI schema: `http://localhost:8000/openapi.json`

FastAPI returns its standard `422` response for a missing/unsupported ticker or
an invalid date. Database connection failures and pool timeouts are logged and
returned as `503 Database unavailable`. Unexpected application/SQL errors remain
`500` responses. Health and documentation routes are technical endpoints; the
required ticker applies to all three price methods.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

API tests exercise the real service, repository and FastAPI lifespan through
an isolated SQLite database. Deribit client and collection tests replace HTTP
requests, so the suite never calls the real exchange or a Redis broker.

The PostgreSQL integration test applies `alembic upgrade head`, compares the
migrated schema against ORM metadata and verifies exact Decimal persistence,
ticker filtering and deterministic ordering. It is skipped unless
`TEST_DATABASE_URL` points to a dedicated PostgreSQL test database:

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://test_user:test_password@localhost:5432/deribit_test
pytest
```

In PowerShell use `$env:TEST_DATABASE_URL = 'postgresql+asyncpg://...'`.
Never point this variable at production: the integration test applies migrations.
Its data writes are rolled back. GitLab CI provides its own PostgreSQL service
and runs the integration test automatically.

Covered cases include all prices, newest price, empty-result `404`, UTC date
filter, required/unsupported ticker, invalid date, valid Deribit parsing, HTTP
errors and malformed Deribit payloads. Regression cases cover strict/extreme
dates, equal timestamps, exact JSON decimals, HTTP session ownership, engine
cleanup, database status codes and collection failures with partial success.

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
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | PostgreSQL container initialization |

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
strings to preserve the exact stored value. JSON numbers are parsed directly
as `Decimal` before reaching the database, without an intermediate `float`.
`NUMERIC(28, 10)` supports 18 integer and 10 fractional digits; PostgreSQL rounds
additional fractional digits to this storage scale.

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

Each ticker has a 25-second budget for fetching and saving. Expected network,
database and timeout failures are logged; the other ticker is still attempted.
After both attempts, any collected errors are raised together so Celery marks
the task as failed while preserving successful writes. Unexpected errors outside
the handled network/database exceptions propagate immediately. There are no
automatic retries: the next scheduled run arrives in one minute.

Beat messages expire after 60 seconds to discard stale queued polls. The task
has a 55-second soft and 60-second hard limit as a worker-level safeguard on
Linux prefork workers. These bounds limit outage backlog; they do not provide
exactly-once delivery or recover samples missed while services are down.

### Resource ownership and module-level objects

FastAPI owns its engine for the application lifespan; each request owns a
session. Each Celery invocation creates and disposes its own engine and HTTP
client inside the event loop started by `asyncio.run()`. No live connection is
shared across event loops or worker processes. Settings are immutable and cached.
Module-level FastAPI/Celery entry points, routers and loggers are framework
registration objects, not shared database or HTTP sessions.

## GitLab CI

`.gitlab-ci.yml` runs Ruff checks and pytest with Python 3.12 and an isolated
PostgreSQL 17 service for integration coverage.
