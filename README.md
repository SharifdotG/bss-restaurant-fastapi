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
uv run python -m app.cli create-admin
uv run fastapi dev
```

API docs are at http://localhost:8000/docs and the health check is at `/api/v1/health`.
There is no public sign up, the first admin is created with the cli and everyone else
is added from `/api/v1/users`.

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
| `SECRET_KEY` | Used to sign access tokens. Required outside `local` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime, default 15 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token lifetime, default 7 |

## Auth

- `POST /auth/login` with `{ email, password }` returns an access token, a refresh token and the user
- Send the access token as `Authorization: Bearer <token>`. When it expires the API answers
  401 with `code: "token_expired"`, call `POST /auth/refresh` with the refresh token to get a new pair
- Refresh tokens are single use. Using an old one again logs out that whole session, so
  only refresh once at a time on the client
- `POST /auth/logout` ends one session, `POST /auth/logout-all` ends all of them
- Roles: `admin`, `manager`, `waiter`, `chef`, `cashier`. Managers can manage staff
  accounts but not admins or other managers

The Authorize button in `/docs` works too, put the email in the username field.

## Tests

Tests run against a real Postgres database called `restaurant_test` (created automatically,
override with `TEST_DATABASE_URL`). With the compose database running:

```bash
uv run pytest
```

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
  services/   business logic, routes stay thin
  cli.py      management commands
alembic/      migrations
tests/
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
