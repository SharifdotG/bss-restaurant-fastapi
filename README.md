# BSS Restaurant API

Backend for a restaurant management system: staff, tables, menu, orders, expenses and reports.
It started as a FastAPI port of [bss-rms](https://github.com/capt-farvez/bss-rms), an ASP.NET Core +
Angular restaurant app. Along the way I'm fixing the things that bothered me there (prices coming
from the client, no roles, images stored as base64 in the database, etc.) and adding features like
online ordering from a QR code and table reservations.

The API is meant to be frontend agnostic so I can build different restaurant frontends on top of it.

## Stack

- Python 3.13+, FastAPI, Pydantic v2
- PostgreSQL ([Neon](https://neon.tech) in production), SQLAlchemy 2.0 async + asyncpg, Alembic
- Cloudflare R2 for images
- Deployed on [FastAPI Cloud](https://fastapicloud.com)
- uv for dependencies, ruff for linting

## Running locally

You need [uv](https://docs.astral.sh/uv/) and either Docker or a Postgres database somewhere
(a Neon branch works fine).

```bash
uv sync
cp .env.example .env

# local postgres, skip this if DATABASE_URL points to neon
docker compose up -d db

uv run alembic upgrade head
uv run fastapi dev
```

API docs are at http://localhost:8000/docs and the health check is at `/api/v1/health`.

## Configuration

Everything is read from environment variables (or `.env`).

| Variable | Description |
| --- | --- |
| `ENVIRONMENT` | `local`, `staging` or `production` |
| `DEBUG` | Verbose logging |
| `DATABASE_URL` | Postgres URL used by the app. For Neon use the **pooled** connection string, it can be pasted as is |
| `DATABASE_URL_DIRECT` | Optional direct (non pooled) URL, used for migrations |
| `DB_ECHO` | Log every SQL statement |
| `CORS_ORIGINS` | Comma separated list of allowed frontend origins |
| `DOCS_ENABLED` | Set to `false` to hide `/docs` and `/openapi.json` |

## Migrations

```bash
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

New models need to be imported in `app/models/__init__.py` so autogenerate can see them.

## Project layout

```
app/
  api/        routers and dependencies
  core/       config, database, errors, logging, pagination helpers
  models/     SQLAlchemy models
  schemas/    request/response models (camelCase over the wire)
alembic/      migrations
```

## API conventions

- All routes live under `/api/v1`
- JSON uses camelCase
- Lists accept `page`, `size` (max 100), `search` and `sort` (`sort=-createdAt,name`) and return
  `{ items, total, page, size, pages }`
- Errors always look like `{ "detail": "...", "code": "..." }`, validation errors also include `errors`

## Deploying

```bash
uv run fastapi deploy
```

Environment variables for the deployed app are set with `fastapi cloud env set` or from the dashboard.
