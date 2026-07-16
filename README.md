# EazyDoctor Backend

FastAPI modular-monolith backend for the doctor/pharmacy appointment booking
platform (Bolpur launch, India-scalable). Built per the Master Build Prompt,
Build Order items 1–6.

## What's included (working, tested to boot)

- **Skeleton**: cloud-agnostic config (env-vars only), Docker, docker-compose,
  Alembic migrations, Modular Monolith folder layout.
- **Auth**: register/login/refresh, JWT access+refresh tokens, bcrypt
  password hashing, role-based guards (patient / merchant / admin / superadmin).
- **Facilities & Doctors**: create facility, add doctors under it, weekly
  availability/leave schedule, search by name/specialty/area + radius filter
  (Haversine now, PostGIS migration path documented in `geo_service.py`).
- **Bookings**: cash-at-checkout working end-to-end; online path wired to a
  `PaymentService` interface with a Paytm stub (see security note below).
  Per-doctor daily token numbering, QR generation (signed UUID, no personal
  data in the QR payload), 5-hour cancellation lock with configurable
  deduction %, cash commission tracked for manual settlement.
- **Queue**: QR check-in (scan = check-in AND current-token advance, no
  separate "complete" step, per spec), manual check-in fallback by Booking ID
  or phone, live-queue read endpoint, 15-minute stall detection endpoint
  (`GET /api/v1/queue/stalled`) meant to be polled by a Celery beat job.
- **Rewards & Earnings ledgers**: both append-only ledgers (not mutable
  balance columns) so history is always auditable. Reward points issued on
  cancellation refunds. Facility withdrawal request flow (payout call is a
  stub — see below).
- **Admin**: per-facility pricing/commission/cancellation overrides, facility
  verification/activation/sponsorship toggles, audit log (SuperAdmin-only
  read), analytics summary endpoint.
- **Service layer abstractions**: `storage_service.py` (Cloudinary today, S3
  swap-in later), `notification_service.py` (Firebase today), `payment_service.py`
  (cash working, Paytm stub). Business logic never imports Cloudinary/Firebase/
  Paytm SDKs directly — only these three files do.
- **Rate limiting**: Redis-backed fixed-window middleware (`app/core/rate_limit.py`),
  keyed by authenticated user id (falls back to client IP), stricter limits on
  `/api/v1/auth/*` and `/api/v1/bookings`, fails open if Redis is unreachable
  so a cache/limiter outage never takes the API down.
- **Caching**: `app/services/cache_service.py` (Redis, JSON) wraps facility
  search results and facility/doctor profile reads; invalidated on writes
  (new facility, new doctor).
- **Background workers (Celery)**: `app/core/celery_app.py` wires Celery beat
  to run the queue-stall sweep every 15 minutes (staff push reminder, then
  escalation to the Admin alert feed if still stuck — see `app/modules/queue/tasks.py`)
  and a 30-minutes-before-appointment push reminder every 5 minutes
  (`app/modules/notifications/tasks.py`). `docker-compose.yml` runs
  `celery_worker` and `celery_beat` alongside the API.

## What's NOT built yet (flagged, not silently skipped)

- **Payments**: only "Pay Cash at checkout" is real. `PaytmPaymentService` in
  `app/services/payment_service.py` is a stub with the right shape but **no
  real checksum verification** — do not deploy online payments off it without
  a dedicated security review once Paytm approval comes through.
- **Payouts**: withdrawal requests are recorded and debited from the ledger,
  but the actual Paytm Payout API call is not wired — same file, same caveat.
- **Banners, ad campaigns/ranking boost, referral system**: not built (Build
  Order items 9–10) — say the word and I'll add them next.
- **2FA for SuperAdmin**: `User.totp_secret` / `is_2fa_enabled` columns exist
  but the actual TOTP enrollment/verification flow isn't implemented yet.
- **PDF export of bookings** (admin panel feature): not built yet — will be
  added as a Celery task once a PDF library is picked.

## Project layout

```
app/
  core/            settings, DB engine, JWT/security, model registry
  common/          shared mixins (UUID PK, timestamps), exceptions
  services/        Storage / Notification / Payment / Geo abstractions
  modules/
    auth/          users, JWT, role guards
    facilities/    facilities + doctors + availability + search
    bookings/      booking creation, QR, cancellation
    queue/         QR/manual check-in, live queue, stall detection
    rewards/       reward points ledger + facility earnings ledger
    admin/         pricing overrides, audit log, analytics
  main.py          FastAPI app + router wiring
alembic/           migrations (env.py reads DATABASE_URL from settings)
Dockerfile
docker-compose.yml  (app + Postgres + Redis for local dev)
.env.example
```

## Running it locally

```bash
cp .env.example .env
# fill in DATABASE_URL if not using docker-compose's built-in Postgres

docker-compose up --build
# API on http://localhost:8000, interactive docs at /docs
```

Without Docker:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# point DATABASE_URL at a running Postgres instance (Supabase connection
# string works as-is)
uvicorn app.main:app --reload
```

In `development` mode the app auto-creates tables on startup for
convenience. For staging/production, use Alembic instead:

```bash
alembic revision --autogenerate -m "init"
alembic upgrade head
```

`docker-compose up` also starts `celery_worker` and `celery_beat` so the
queue-stall sweep and appointment reminders run automatically. Without
Docker, run them in two extra terminals:

```bash
celery -A app.core.celery_app worker --loglevel=info
celery -A app.core.celery_app beat --loglevel=info
```

## Quick manual test flow

1. `POST /api/v1/auth/register` — role `merchant` → login → get access token
2. `POST /api/v1/facilities` (as merchant) → note `facility_id`
3. `POST /api/v1/facilities/{facility_id}/doctors` → note `doctor_id`
4. Register/login a second user as role `patient`
5. `POST /api/v1/bookings` with `payment_mode: "cash"` → returns booking +
   `qr_code_base64` (decode to see the QR PNG)
6. As merchant: `POST /api/v1/queue/check-in/qr` with the returned `qr_uuid` +
   `qr_signature` (both are in the booking response as `qr_uuid`/parseable
   from the QR payload) → queue advances
7. `GET /api/v1/queue/live/{doctor_id}?date=YYYY-MM-DD` → see current token

## Migration to AWS later

Only environment variables change:
- `DATABASE_URL` → AWS RDS Postgres connection string
- `STORAGE_PROVIDER=s3` + AWS credentials (once an `S3StorageService` class
  is added implementing the same `StorageService` interface)
- Same Docker image runs on ECS/EC2 unmodified

No business logic, models, or module structure should need to change for
this migration — that's the whole point of the service-layer abstractions.
