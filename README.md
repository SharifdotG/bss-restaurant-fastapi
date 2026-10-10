# BSS Restaurant API

Backend for a restaurant management system: staff, tables, menu, orders, bills and payments,
expenses, reports, table bookings, customer ordering from a QR code or a website, and live
updates for kitchen screens.
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

To have something to click around in, fill an empty database with demo data:

```bash
uv run python -m app.cli seed-demo
```

It adds a menu (Bangladeshi dishes, prices in taka), 10 tables, a manager, cashier, two
waiters and a chef with logins (`manager@example.com` and so on, the password is printed at
the end), about a month of paid orders, a few orders in the kitchen right now, expenses and
bookings. It only runs on an empty database, and refuses `ENVIRONMENT=production` unless you
pass `--allow-production`. `--days` and `--seed` change how much and which data you get.

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
| `LIVE_BACKEND` | `memory` (default, one instance) or `postgres` to pass live updates between instances, see Live updates |
| `RATE_LIMIT_ENABLED` | Login and public endpoints are rate limited per ip, default `true` |
| `TRUSTED_PROXY_HOPS` | Number of proxies in front of the app, used to read the client ip from `X-Forwarded-For`. Default 0 (use the connection address) |
| `CLIENT_IP_HEADER` | Header with the real client ip that the edge proxy sets and clients can't fake. Wins over `TRUSTED_PROXY_HOPS`. On FastAPI Cloud set it to `cf-connecting-ip` |
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
- Logging in is rate limited: 20 attempts a minute per ip and 5 per 5 minutes for one
  account from the same ip, after that the API answers 429 with a `Retry-After` header
- Roles: `admin`, `manager`, `waiter`, `chef`, `cashier`. Managers can manage staff
  accounts but not admins or other managers

The Authorize button in `/docs` works too, put the email in the username field.

## What's in there

| Area | Endpoints | Notes |
| --- | --- | --- |
| Restaurant | `/restaurant` | Name and details for receipts, currency, VAT and service charge, opening hours and booking settings |
| Users | `/users` | Admins and managers manage staff accounts, nothing is hard deleted |
| Uploads | `POST /uploads/images` | Upload first, then send the returned `key` as `imageKey`. Images are checked, resized and stored as webp |
| Menu | `/categories`, `/foods` | Discounts are percentage or flat, the final price is always calculated by the server. Chefs can mark food as sold out |
| Tables | `/tables` | `isOccupied` comes from open orders, every table has a QR token for customer ordering. `PUT /tables/{id}/employees` sets who serves it |
| Employees | `/employees` | HR details, optionally with a login account created in the same request |
| Orders | `/orders` | See below |
| Payments | `/orders/{id}/payments`, `/orders/{id}/refunds`, `/orders/{id}/receipt` | See below |
| Reservations | `/reservations` | See below |
| Expenses | `/expenses` | Categorised, with an optional receipt photo |
| Dashboard | `GET /dashboard` | Managers and cashiers. See below |
| Public | `/public/*` | No login, for customer facing sites. See below |
| Reports | `/reports/*` | Managers only. See below |
| Live | `ws /live` | Websocket with order and booking changes for kitchen and floor screens. See below |

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
  chefs move orders through the kitchen, managers can do everything
- `paid` is never set by hand, it happens when the bill is settled (see below)
- `nextStatuses` on every order tells the frontend which buttons to show
- The item list can be replaced until the kitchen starts, after that items can only be added
- Paid and cancelled orders are read only

### Bills and payments

VAT and service charge come from `/restaurant`. The rates are copied onto the order when it's
placed, so changing them later doesn't touch open orders. Service charge is only added to dine
in orders and VAT is charged on top of it. Every order shows `subtotal`, `discountTotal`,
`serviceCharge`, `vat`, `total`, `amountPaid` and `balanceDue`.

- Cashiers and managers take payments with `POST /orders/{id}/payments`:
  `{ "method": "cash" | "card" | "mobile", "amount"?, "tendered"?, "reference"? }`.
  Leave out `amount` to pay whatever is left. For cash, `tendered` is what the customer
  handed over and the change is worked out. Mobile payments (bKash, Nagad, ...) need the
  transaction id as `reference`
- A split bill is just several payments, paying more than what's left is refused
- Once the bill is settled a served order becomes `paid` by itself. Takeaway paid at the
  counter closes when it's handed over (`served`)
- Managers give money back with `POST /orders/{id}/refunds` (needs a `reason`). An order that
  still holds money can't be cancelled, refund it first
- `GET /orders/{id}/receipt` returns a printable html bill (open order) or receipt (paid),
  sized for 80mm thermal printers. Add `?print=true` to open the print dialog right away

### Customer ordering (public API)

Everything under `/public` works without logging in, so a restaurant website or a QR code
page can be built on top of it. Customers only ever send what they want, prices come from
the menu like for staff orders.

| Endpoint | What it does |
| --- | --- |
| `GET /public/restaurant` | Name, contact details, currency, VAT and service charge, which kinds of ordering are on |
| `GET /public/menu` | Visible categories with their foods in one call. Sold out foods are included with `isAvailable: false` |
| `GET /public/tables/{qrToken}` | The table behind a QR code |
| `POST /public/tables/{qrToken}/orders` | Order from the table, `{ items, customerName?, customerPhone?, notes? }` |
| `POST /public/orders` | Online takeaway, needs `customerName` and `customerPhone` |
| `GET /public/orders/{trackingCode}` | Status, items and bill of an order |
| `POST /public/orders/{trackingCode}/cancel` | Customers can cancel their own order while it's pending (`canCancel`) |
| `GET /public/reservations/slots?day=&partySize=` | Times on a day a party can book, see Reservations |
| `POST /public/reservations` | Book a table, `{ startsAt, partySize, customerName, customerPhone, customerEmail?, notes? }` |
| `GET /public/reservations/{trackingCode}` | Status and table of a booking |
| `POST /public/reservations/{trackingCode}/cancel` | Until the booking time (`canCancel`) |

- Every order has a `trackingCode` (staff orders too, so it can be printed or texted). It's
  random on purpose, order numbers are easy to guess
- QR and online orders wait as `pending` until staff confirm them, the waiter who confirms
  becomes the order's waiter. `GET /orders?source=qr&source=online&status=pending` is the
  "incoming" list
- A table can have at most 3 unconfirmed QR orders and a phone number 3 unconfirmed online
  orders, to keep pranks out of the kitchen. If a QR code leaks, `POST /tables/{id}/qr-token`
  gives the table a new one
- QR ordering is on and online ordering is off by default, see `acceptsQrOrders` and
  `acceptsOnlineOrders` on `/restaurant`
- Placing and cancelling orders (and bookings, counted separately) is limited to 10
  requests per 10 minutes per ip, reading
  to 120 a minute. The limiter is in memory, so with more than one instance each one counts
  on its own

### Reservations

A booking holds one table from `startsAt` for the restaurant's `reservationMinutes`
(90 by default, or `minutes` per booking).

```
requested ──> confirmed ──> seated ──> completed
   │              │
   │              ├──> no_show
   │              └──> cancelled
   ├──> declined
   └──> cancelled
```

- Staff bookings (`POST /reservations`) are confirmed straight away. Leave out `tableId` and
  the smallest free table that fits is picked, so a couple doesn't end up at the table for
  eight. `GET /reservations/availability?startsAt=&partySize=` lists the free tables
- Only `confirmed` and `seated` bookings hold a table. Postgres refuses overlapping bookings
  of one table with an exclusion constraint (`btree_gist`), so two people booking the last
  table at the same moment can't both get it. A booking ending at 20:30 and one starting at
  20:30 don't overlap
- Moving a booking (`PATCH /reservations/{id}`) checks its table again for the new time and
  party size. Seated and finished bookings can't be changed
- Cancelling and declining need a `note`, the customer sees it. `no_show` only once the
  booking time has passed
- `GET /reservations?dateFrom=2026-10-10` is the day's list, sorted by time.
  `?status=requested` shows website bookings waiting for an answer

Website bookings are off until a manager sets `acceptsReservations` on `/restaurant`:

- `GET /public/reservations/slots` gives the start times (every 30 minutes from opening)
  with at least one table free. `opensAt`/`closesAt` are local times, a closing time before
  the opening time means open past midnight
- Bookings must be at least an hour ahead, at most 60 days ahead, inside opening hours and
  for up to 20 people. Bigger groups should call
- A phone number can have 3 upcoming bookings
- They come in as `requested` without a table, staff confirm them (a table is picked if none
  is given). With `autoConfirmReservations` a free table is given out straight away instead
- Customers can cancel with the `trackingCode` until the booking starts

### Dashboard and reports

All money figures only count **paid** orders, and an order counts on the day it was paid.
Days are restaurant days (`RESTAURANT_TZ`), so a sale at 00:30 belongs to that morning even
though it's still the previous day in UTC. Sales are what customers paid, profit is sales
minus VAT, refunds and expenses. A refund counts on the day it was given, but only when the
order was already paid (refunding a wrong payment before that isn't lost money).

| Endpoint | What you get |
| --- | --- |
| `GET /dashboard` | Today, this month, this year and all time (orders, sales, expenses, profit, average order), open orders per status, table occupancy, today's bookings and guests, booking requests waiting, recent orders, best sellers this month |
| `GET /reports/sales` | One row per `groupBy=day\|week\|month\|year`, days without sales included so charts have no holes |
| `GET /reports/top-foods` | Best sellers, optional `categoryId` and `limit` |
| `GET /reports/staff` | Orders, items and sales per waiter |
| `GET /reports/expenses` | Expenses per category with their share |

Every report takes `dateFrom` and `dateTo` (both included, default is the current month so far).
Add `.csv` to any of them (`/reports/sales.csv`, ...) to download it for Excel, and
`/reports/orders.csv` gives every paid or cancelled order in the range, one per line.

### Live updates

`/api/v1/live` is a websocket that pushes order and booking changes as they happen, so
kitchen and floor screens don't have to poll. Browsers can't put headers on a websocket,
and tokens in the url end up in logs, so the token goes in the first message:

```js
const ws = new WebSocket("wss://<host>/api/v1/live?topics=orders")
ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: accessToken }))
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data)
  // authenticated, snapshot, order.created, order.updated, reservation.created, ...
}
```

| Message | When |
| --- | --- |
| `authenticated` | After each auth message, with the user and `expiresIn` (seconds) |
| `snapshot` | Right after connecting: open `orders` and, for `reservations`, today's bookings, seated guests and unanswered requests |
| `order.created`, `order.updated` | `data` is the order with its items, table, waiter, status and balance |
| `reservation.created`, `reservation.updated` | `data` is the booking |
| `snapshot` again | When the server thinks the screen missed something (it fell behind, or the postgres relay reconnected). Replace everything you have |
| `ping` | Every 25 seconds when nothing happens, so proxies keep the connection open |

- Treat events as "upsert by id": `order.updated` covers status changes, edits and
  payments. Drop an order once its status is `paid` or `cancelled`
- `?topics=orders,reservations` picks what to follow, both by default. Chefs only get
  orders
- The connection ends with the access token. Send another `{"type": "auth", "token": ...}`
  with a fresh token before `expiresIn` runs out to keep it. `{"type": "ping"}` gets a
  `pong`
- Close codes: `4401` no or bad token, or it ran out (the reason says `token_expired`),
  `4403` topic not allowed for the role, `4400` bad message or unknown topic. Reconnect
  after anything else, the snapshot catches you up

With more than one instance (FastAPI Cloud scales on its own) set `LIVE_BACKEND=postgres`,
otherwise screens only hear about changes made on the instance they are connected to.
Events then go through postgres `LISTEN/NOTIFY`:

- Listening uses a direct connection (Neon's pooler can't `LISTEN`), opened only while the
  instance has screens connected
- An idle listening connection doesn't stop Neon's scale to zero: after a few quiet minutes
  the database suspends and drops it. The relay reconnects (which wakes the database) and
  screens get a fresh snapshot, so nothing is lost, but with screens connected the database
  hardly sleeps. Neon recommends turning scale to zero off for `LISTEN`
- A NOTIFY can't carry more than 8000 bytes. A huge order arrives with only its id and
  `"partial": true`, fetch it with `GET /orders/{id}`

## Tests

Tests run against a real Postgres database called `restaurant_test` (created automatically,
override with `TEST_DATABASE_URL`). With the compose database running:

```bash
uv run pytest
```

GitHub Actions runs ruff, the tests (against a postgres service) and `alembic check` on every
push and pull request, see `.github/workflows/ci.yml`.

## Migrations

```bash
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

New models need to be imported in `app/models/__init__.py` so autogenerate can see them.

The reservations migration turns on the `btree_gist` extension, Neon and the postgres
image in `compose.yaml` both have it.

## Project layout

```
app/
  api/        routers and dependencies
  core/       config, database, errors, logging, pagination, rate limits, live update hub
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

The app runs on FastAPI Cloud, which finds `app.main:app` through `[tool.fastapi]` in
`pyproject.toml`.

1. Set the environment variables, secrets with `--secret`:

   ```bash
   uv run fastapi cloud env set ENVIRONMENT production
   uv run fastapi cloud env set --secret SECRET_KEY "<random, 32+ characters>"
   uv run fastapi cloud env set --secret DATABASE_URL "<neon pooled url>"
   uv run fastapi cloud env set CORS_ORIGINS "https://your-frontend.example"
   uv run fastapi cloud env set CLIENT_IP_HEADER cf-connecting-ip
   ```

   Plus `STORAGE_BACKEND=r2` with the `R2_*` settings, and if you like `DOCS_ENABLED=false`
   and `LIVE_BACKEND=postgres` (see Configuration).

   `CLIENT_IP_HEADER` matters: FastAPI Cloud's uvicorn takes the client ip from the first
   `X-Forwarded-For` entry, which anyone can set. Without it the login rate limits can be
   dodged with a different made up ip on every request. Cloudflare in front sets
   `CF-Connecting-IP` and refuses requests that try to send it themselves

2. Run the migrations against the production database from your machine. Migrations so far
   only add things, so they go **before** the deploy and the old version keeps working
   during the gradual rollout:

   ```bash
   DATABASE_URL="<neon pooled url>" uv run alembic upgrade head
   ```

   On a new database create the first admin the same way with `create-admin`

3. Deploy and check it's alive:

   ```bash
   uv run fastapi deploy
   curl https://<your app url>/api/v1/health
   ```

A migration that removes or renames something has to go **after** the deploy that stops
using it.

## Credits

The data model and the original feature set come from
[bss-rms](https://github.com/capt-farvez/bss-rms) by capt-farvez. This is a rewrite in a
different stack, not a fork, but it wouldn't exist without it.
