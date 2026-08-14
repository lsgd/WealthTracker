---
name: run-wealth-web
description: Run, start, or screenshot the Wealth Tracker web app locally — Django backend on port 8085 + React/Vite frontend — seeded with demo/test data, driven via a Playwright login-and-screenshot driver and curl API smoke tests.
---

# Run the Wealth Tracker web app (with demo data)

Django REST backend (`backend/`) + React/Vite frontend (`frontend/`). The vite dev
server proxies `/api` to `http://localhost:8085`, so the backend **must** run on 8085.
Drive it with the Playwright driver at `.claude/skills/run-wealth-web/driver.py`
(all paths in this file are relative to the repo root). Verified on macOS with the
repo's existing `venv/` and `frontend/node_modules/`.

## Prerequisites

- Python venv at repo root: `source venv/bin/activate` (Playwright is already a
  backend dependency — no separate install).
- Frontend deps: `cd frontend && npm install` (fast no-op if already present).

## Setup: migrate + demo data

```bash
cd backend && source ../venv/bin/activate
python manage.py migrate
python manage.py loaddata initial_brokers.json
python manage.py generate_demo_data --users demo1:demo12345
```

`generate_demo_data` creates the `demo1` user with 5 accounts and ~2.5 years of
snapshot history. Safe to re-run: it deletes and recreates only users flagged
`is_demo_user`; it refuses to touch a real user with the same name.

## Run (agent path)

Start both servers in the background:

```bash
cd backend && source ../venv/bin/activate && python manage.py runserver 8085 --noreload
```

```bash
cd frontend && npm run dev
```

**Read the vite output for the real port.** It asks for 5173 but silently falls
back to 5174+ when 5173 is busy (see Gotchas). Then drive the app:

```bash
source venv/bin/activate
python .claude/skills/run-wealth-web/driver.py --url http://localhost:5173 --shot /tmp/wealth-dashboard.png
```

The driver logs in as `demo1`/`demo12345` through the real login form, waits for
the dashboard, saves a full-page screenshot, and exits non-zero if the dashboard
did not render. **Look at the screenshot.**

### API smoke (curl)

Auth uses a custom header — `X-Auth-Token: Bearer <jwt>`, **not** `Authorization`
(that name is reserved to avoid a Basic-Auth conflict; plain `Authorization`
returns 401 "credentials were not provided" even with a valid token):

```bash
TOKEN=$(curl -s -X POST http://localhost:8085/api/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo1","password":"demo12345"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access'])")
curl -s http://localhost:8085/api/accounts/ -H "X-Auth-Token: Bearer $TOKEN" | head -c 300
```

## Run (human path)

Same two servers, then open the vite URL in a browser and log in as
`demo1`/`demo12345`. Django admin is at `http://localhost:8085/admin/`
(needs `python manage.py createsuperuser`; the demo user is not staff).

## Test

```bash
cd backend && source ../venv/bin/activate && python manage.py test
```

## Gotchas

- **Backend port is 8085, not 8000** — hardcoded as the proxy target in
  `frontend/vite.config.ts`. `runserver` without the port argument breaks the
  frontend silently.
- **Another local app may hold port 5173.** Vite then starts on 5174 without
  failing. Symptom of hitting the wrong app: `/api` requests answered by
  `server: uvicorn` with a 307 redirect to `localhost:8000`. Always confirm the
  port from vite's startup output and pass it to the driver via `--url`.
- **`X-Auth-Token` header** — see API smoke above. Easy to lose an hour on.
- **Playwright browser-build mismatch**: the venv's Playwright may expect e.g.
  `chromium_headless_shell-1234` while the cache has `-1223` ("Executable
  doesn't exist… run playwright install"). No download needed — the driver
  falls back to the newest cached `chrome-headless-shell` automatically.
- The demo data contains **no transactions** (feature lives on the
  `feat/transactions` branch; on that branch, seed rows via the ORM or the
  `POST /api/accounts/<id>/transactions/` endpoint).

## Troubleshooting

- `curl http://localhost:5173/... → 307 + server: uvicorn` → you are talking to
  a different project squatting on 5173; use the port vite actually printed.
- `401 {"detail": "Authentication credentials were not provided."}` with a valid
  JWT → you sent `Authorization:`; use `X-Auth-Token: Bearer <token>`.
- `BrowserType.launch: Executable doesn't exist at …chromium_headless_shell-…`
  → cached-build fallback in the driver handles it; if the cache is empty, run
  `playwright install chromium --only-shell` once.
