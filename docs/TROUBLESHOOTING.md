# Local development — troubleshooting

Real gotchas hit while running the full Docker stack locally, with the exact fix. Symptom → cause → fix.

## Frontend login times out on `https://localhost:8443`

**Symptom.** The login page shows *"Couldn't reach the server at https://localhost:8443"*, or a request to it just hangs / `ERR_TIMED_OUT`. The app itself was working minutes earlier.

**Cause.** `app` and `app-tls` run `uvicorn --reload` with a file watcher (see `docker-compose.yml`). A rapid burst of source edits can leave one reload wedged in `Shutting down` → `Waiting for background tasks to complete.` — a long-lived background task (an open WebSocket relay such as `/stream/portfolio`, or the tick listener) doesn't return, so uvicorn never finishes the reload and the server stops accepting connections. The container stays `Up` (the process is alive, just stuck), so `docker compose ps` looks fine.

**Confirm it.** `docker compose logs app-tls --tail 20` ends on `Waiting for background tasks to complete. (CTRL+C to force quit)` with nothing after it.

**Fix.**

```bash
docker compose restart app app-tls
```

Then `POST /api/v1/auth/login` returns `200` again. If you're editing many files at once, expect to do this occasionally.

## A fresh Postgres / data-lake volume comes up empty

**Symptom.** Login fails with *"Incorrect email or password"* for the default account; the `app` container crash-loops on `password authentication failed for user "tradingos_app"`; the Candlestick Chart shows *"RECONNECTING…"* and `GET /market/symbols` returns `[]`; a handful of `test_backtest_real_data` / `test_corporate_actions_backtest_diff` / `test_real_backtest_runner` tests fail on a missing date window.

**Cause.** A reset (or brand-new) `tradingos_app_postgres_data` / `tradingos_app_data_lake` volume has no schema, no `tradingos_app` role (a migration creates it), no seeded users, and no market data.

**Fix — the standard per-environment bootstrap:**

```bash
docker compose exec app alembic upgrade head          # 37+ migrations; creates the tradingos_app role
docker compose restart app app-tls
docker compose exec app python scripts/seed_admin_user.py     # admin@tradingos.local / dev-only-change-me
docker compose exec app python scripts/seed_paper_account.py  # the ₹1,00,000 Paper account

# market data (equities/indices/futures + options catalog, then OHLCV):
docker compose exec app python -m src.data.ingest.instrument_sync --exchange NSE
docker compose exec app python -m src.data.ingest.pipeline --source managed \
  --symbols RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK --start 2023-07-21 --end 2024-07-19
docker compose exec app python -m src.data.ingest.pipeline --source yfinance \
  --symbols '^NSEI' --start 2023-07-21 --end 2024-07-19
```

`instrument_sync` also seeds ~66k NSE F&O option contracts (REL-088) — that pass alone takes a minute or two.

## A non-Chrome browser (or Cypress) can't log in — self-signed cert

**Symptom.** Login works in your everyday Chrome but not in a fresh browser profile, an automation browser, or `cypress run` from the host — the frontend's calls to `https://localhost:8443` silently fail.

**Cause.** `NEXT_PUBLIC_API_BASE_URL` defaults to the real-TLS `app-tls:8443` service (GLH-02), which uses a self-signed dev cert (`docker/`). A browser that hasn't accepted that cert once will refuse the `fetch`/WebSocket calls the way `curl` without `-k` would.

**Fix.** Either open `https://localhost:8443` directly once and accept the warning, or point the frontend at the plain-HTTP port for the run and restore it after:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8001 docker compose up -d --force-recreate frontend
# ... do the run ...
docker compose up -d --force-recreate frontend        # restores the https://localhost:8443 default
```

`.github/workflows/ci.yml` uses `http://app:8000` for the same reason.

## `npm ci` in the Cypress container fails with `EAI_AGAIN registry.npmjs.org`

**Symptom.** A local `cypress/included` run dies at `npm ci` on a DNS resolution error.

**Cause.** This host's Docker embedded DNS isn't reachable from inside a user-defined bridge network.

**Fix.** Add explicit resolvers to the `docker run`: `--dns 1.1.1.1 --dns 8.8.8.8`.
