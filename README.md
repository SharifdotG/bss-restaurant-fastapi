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
| `DATABASE_URL_DIRECT` | Optional. Migrations use the direct (non pooled) connection, for Neon it's worked out from `DATABASE_URL` so this is rarely needed |
| `DB_ECHO` | Log every SQL statement |
| `CORS_ORIGINS` | Comma separated list of allowed frontend origins |
| `DOCS_ENABLED` | Set to `false` to hide `/docs` and `/openapi.json` |
| `SECRET_KEY` | Used to sign access tokens. Required outside `local` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime, default 15 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token lifetime, default 7 |
| `RESTAURANT_TZ` | Timezone of the restaurant, default `Asia/Dhaka`. Order numbers and "today" follow it |
| `STORAGE_BACKEND` | `local` (files in `LOCAL_UPLOAD_DIR`, served from `/media`) or `r2` |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Cloudflare R2 API token with read/write access to the bucket |
| `R2_BUCKET`, `R2_PUBLIC_URL` | Bucket name and its public url (r2.dev or a custom domain) |
| `MAX_UPLOAD_MB` | Upload size limit, default 5 |

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

## What's in there

| Area | Endpoints | Notes |
| --- | --- | --- |
| Users | `/users` | Admins and managers manage staff accounts, nothing is hard deleted |
| Uploads | `POST /uploads/images` | Upload first, then send the returned `key` as `imageKey`. Images are checked, resized and stored as webp |
| Menu | `/categories`, `/foods` | Discounts are percentage or flat, the final price is always calculated by the server. Chefs can mark food as sold out |
| Tables | `/tables` | `isOccupied` comes from open orders, every table has a QR token for customer ordering. `PUT /tables/{id}/employees` sets who serves it |
| Employees | `/employees` | HR details, optionally with a login account created in the same request |
| Orders | `/orders` | See below |
| Expenses | `/expenses` | Categorised, with an optional receipt photo |
| Dashboard | `GET /dashboard` | Managers and cashiers. See below |
| Reports | `/reports/*` | Managers only. See below |

### Orders

The client only sends what was ordered (`foodId`, `quantity`, optional `notes`). Prices, discounts
and totals are taken from the menu at that moment and stored on the order, so changing a price
later doesn't touch old orders. Order numbers look like `261002-0007` (date + counter for that day).

Status flow, every step is recorded in the order history:

```
pending -> confirmed -> preparing -> ready -> served -> paid
   \____________\___________\-> cancelled (needs a reason)
```

- Each step can only be done by the roles that do it in practice: waiters confirm and serve,
  chefs move orders through the kitchen, cashiers take payment, managers can do everything
- `nextStatuses` on every order tells the frontend which buttons to show
- The item list can be replaced until the kitchen starts, after that items can only be added
- Paid and cancelled orders are read only

### Dashboard and reports

All money figures only count **paid** orders, and an order counts on the day it was paid.
Days are restaurant days (`RESTAURANT_TZ`), so a sale at 00:30 belongs to that morning even
though it's still the previous day in UTC. Profit is sales minus expenses.

| Endpoint | What you get |
| --- | --- |
| `GET /dashboard` | Today, this month, this year and all time (orders, sales, expenses, profit, average order), open orders per status, table occupancy, recent orders, best sellers this month |
| `GET /reports/sales` | One row per `groupBy=day\|week\|month\|year`, days without sales included so charts have no holes |
| `GET /reports/top-foods` | Best sellers, optional `categoryId` and `limit` |
| `GET /reports/staff` | Orders, items and sales per waiter |
| `GET /reports/expenses` | Expenses per category with their share |

Every report takes `dateFrom` and `dateTo` (both included, default is the current month so far).
Add `.csv` to any of them (`/reports/sales.csv`, ...) to download it for Excel, and
`/reports/orders.csv` gives every paid or cancelled order in the range, one per line.

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
