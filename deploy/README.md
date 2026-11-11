# Deploying ScamShield AI

ScamShield AI is two processes:

| Process | What it is | Default port | Entry point |
|---|---|---|---|
| **API** | FastAPI + ML model + rule engine + SQLite | `8000` | `backend.main:app` (uvicorn) |
| **UI** | Streamlit dashboard talking HTTP to the API | `8501` | `frontend/app.py` |

The UI **never** loads the ML model itself — it only calls the API. That means you
can scale or restart either side independently, and the UI can be hosted anywhere
(including Streamlit Community Cloud) as long as it can reach the API.

There are three supported paths. Pick one.

---

## Path 1 — Docker Compose (recommended, reproducible)

**Requirements:** Docker Engine 24+ with the Compose v2 plugin.

```bash
# from the project root
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs -f api
```

What you get:

- `api` — multi-stage image, runs as non-root **uid 1001**, `WEB_CONCURRENCY=2` uvicorn workers, container `HEALTHCHECK` on `/api/v1/health`, model warmed at startup.
- `ui` — Streamlit on `8501`, configured to reach the API over the compose network (`http://api:8000`), not `localhost`.
- `scamshield-data` — a **named volume** for `data/scamshield.db`, so scan history survives `docker compose down` / image rebuilds.

Verify from the host:

```bash
python scripts/prod_smoke_test.py --api http://localhost:8000 --ui http://localhost:8501
```

### Adding PostgreSQL

The schema layer is written for PostgreSQL too; SQLite is the default only because
it needs no server.

```bash
# 1. in .env (never committed):
#    DATABASE_URL=postgresql+psycopg://scamshield:CHANGE_ME@postgres:5432/scamshield
docker compose -f deploy/docker-compose.yml --profile postgres up -d --build
```

Tear everything down (keeps the volume):

```bash
docker compose -f deploy/docker-compose.yml down
```

Add `-v` only if you deliberately want to **delete all scan history**.

---

## Path 2 — systemd + nginx (a Linux VM / VPS)

Use this on a plain Ubuntu/Debian box where you want the services managed by the
init system rather than containers.

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin scamshield
sudo mkdir -p /opt/scamshield && sudo chown -R scamshield:scamshield /opt/scamshield
# copy the project to /opt/scamshield, then:
sudo -u scamshield python3 -m venv /opt/scamshield/.venv
sudo -u scamshield /opt/scamshield/.venv/bin/pip install -r /opt/scamshield/requirements.txt
sudo -u scamshield cp /opt/scamshield/.env.example /opt/scamshield/.env   # then edit it
```

Install the units and the reverse proxy:

```bash
sudo cp deploy/scamshield-api.service /etc/systemd/system/
sudo cp deploy/scamshield-ui.service  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now scamshield-api scamshield-ui
sudo systemctl status scamshield-api --no-pager

sudo cp deploy/nginx.conf /etc/nginx/sites-available/scamshield
sudo ln -s /etc/nginx/sites-available/scamshield /etc/nginx/sites-enabled/scamshield
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d api.example.com -d app.example.com   # TLS
```

`deploy/nginx.conf` already provides:

- TLS termination + HTTP→HTTPS redirect, HSTS, CSP, `X-Frame-Options`.
- **Rate limiting**: `30r/m` per IP for `/api/v1/scan/`, so one client cannot brute-force cost out of the service.
- The `Upgrade`/`Connection` map Streamlit's WebSocket needs — without it the dashboard loads and then hangs on "Please wait…".

Both units are hardened (`NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`,
a writable `StateDirectory` for the database) — read them before deploying; they
document each directive in a comment.

---

## Path 3 — Managed PaaS (Render / Railway / Fly.io / Streamlit Cloud)

> **Step-by-step walkthrough: [`../docs/START_HERE_DEPLOY.md`](../docs/START_HERE_DEPLOY.md)**
> (9 steps, with the expected output at each one). Troubleshooting tables live in
> [`../docs/DEPLOY_RENDER.md`](../docs/DEPLOY_RENDER.md). It also covers the one
> trap of PaaS deployment: `.gitignore` excludes the trained model, so a plain
> `git push` deploys an API with no ML layer. Use
> `python scripts/export_for_git.py` to build the Git-ready folder.


**API** (any host that runs a Dockerfile or a Python service):

```
Build:  docker build -f deploy/Dockerfile.api -t scamshield-api .
Start:  uvicorn backend.main:app --host 0.0.0.0 --port $PORT \
          --workers 2 --proxy-headers --forwarded-allow-ips='*'
Health: /api/v1/health
```

`render.yaml` in the project root is a ready-made Render Blueprint for this path.
The container binds to `$PORT` (falling back to 8000 locally), and the SQLite
path can be redirected with `DATA_DIR=/mounted/disk` without editing the URL.

**UI** on Streamlit Community Cloud — point it at `frontend/app.py` and add these
to *Settings → Secrets* (see `frontend/.streamlit/secrets.toml.example`):

```toml
API_BASE_URL = "https://your-api-host.example.com"
API_KEY = "the-same-value-as-API_KEY-on-the-api"
```

Because the UI reads `API_BASE_URL` from secrets, no code changes are needed
between local and cloud.

---

## Environment variables

Copy `.env.example` → `.env` and fill it in. `.env` is git-ignored and is **excluded
from `ScamShield-AI.zip`** — it must never be committed or shared.

| Variable | Default | Why it matters |
|---|---|---|
| `ENVIRONMENT` | `development` | Set to `production` on a real deployment. `/api/v1/health` reports it, and it documents the intent for operators. |
| `DEBUG` | `false` | Leave `false` in production. Verbose tracebacks belong in logs, not in HTTP responses. |
| `LOG_LEVEL` | `INFO` | `INFO` gives one line per request (`POST /api/v1/scan/message -> 200 (18.4 ms)`). |
| `API_KEY` | *(empty)* | If set, `/api/v1/scan/*` and `/api/v1/history/*` require the `X-API-Key` header. Set it on any instance reachable from the internet, and give the UI the same value. |
| `CORS_ORIGINS` | `http://localhost:8501,http://127.0.0.1:8501` | Comma-separated browser origins allowed to call the API. Add your UI's real origin in production. |
| `DATABASE_URL` | `sqlite:///./data/scamshield.db` | Swap for PostgreSQL without touching code: `postgresql+psycopg://user:pass@host:5432/scamshield`. |
| `WEB_CONCURRENCY` | `2` | uvicorn workers (read by the Dockerfile CMD and by `backend/main.py`). Each worker holds its own copy of the model, which is only ~160 KB, so 2–4 is cheap. |
| `GEMINI_API_KEY` | *(empty)* | Optional. **Without it the app still works** — explanations fall back to templates and the UI reports `source: fallback`. |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Model used for explanations only; the ML verdict never depends on Gemini. |
| `GEMINI_ENABLED` | `true` | Set `false` to force the deterministic fallback even when a key exists. |
| `ML_SPAM_THRESHOLD` | `0.50` | Decision boundary for the spam label. Lower it to catch more spam at the cost of false positives. |
| `STORE_RAW_MESSAGE` | `true` | Set **`false`** in production: only a salted hash + redacted preview are persisted, never the plaintext. |
| `PRIVACY_SALT` | dev placeholder | Salt for the message fingerprint hash. **Change it** before storing real user data. |
| `HISTORY_MAX_ROWS` | `5000` | Retention ceiling; the oldest rows are trimmed automatically. |
| `API_BASE_URL` | `http://localhost:8000` | UI-side only: where the dashboard finds the API. Read from Streamlit secrets in the cloud. |

There is no in-process HTTP rate limiter in the application — abuse protection is
deployed at the edge, which is where it belongs (`deploy/nginx.conf` ships
`30r/m` per IP on `/api/v1/scan/`). If you deploy without nginx, add the equivalent
rule at your load balancer or CDN.

Production `.env` minimum:

```ini
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO
API_KEY=<long random string>            # and give the UI the same value
STORE_RAW_MESSAGE=false
PRIVACY_SALT=<long random string>
CORS_ORIGINS=https://app.example.com
DATABASE_URL=postgresql+psycopg://scamshield:CHANGE_ME@postgres:5432/scamshield
```

Generate the two secrets with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

---

## Post-deploy verification

Every deployment should end with the smoke test — it is the difference between
"the container started" and "the product works":

```bash
python scripts/prod_smoke_test.py \
  --api https://api.example.com \
  --ui  https://app.example.com \
  --api-key "$API_KEY"
```

It checks 12 things (API health, DB, model, Gemini status, measured model metrics,
a known scam sample scoring `critical`, a benign control scoring `low`, the stats
endpoint, and a real HTTP call to the UI) and exits **0** on success, **1** on any
failure — so it can be dropped straight into CI or a deploy hook.

To regenerate the report of real outputs afterwards:

```bash
python scripts/capture_outputs.py --api https://api.example.com --ui https://app.example.com
```

---

## Running the "production profile" without Docker

Useful for a demo or a lab machine where containers are not available. Same code
path as the containers: no reload, 2 workers, proxy headers respected.

```bash
# Linux / macOS
ENVIRONMENT=production DEBUG=false WEB_CONCURRENCY=2 \
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 \
  --workers 2 --proxy-headers --forwarded-allow-ips='*'

# Windows (PowerShell)
$env:ENVIRONMENT="production"; $env:DEBUG="false"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers
```

Then the UI in a second terminal: `python -m streamlit run frontend/app.py`.

---

## Operational notes

- **The database is the only stateful thing.** Back it up with
  `sqlite3 data/scamshield.db ".backup data/backup.db"` (safe while running) or use
  `pg_dump` for PostgreSQL.
- **The schema is self-healing**: if the DB file is deleted, the next request
  recreates the tables instead of returning HTTP 500. History is lost, the service
  is not.
- **Scaling out**: multiple workers/containers are fine — inference is stateless.
  Only the SQLite file needs a shared volume; with more than one host, use PostgreSQL.
- **What this stack does not include**: a task queue, user accounts, or a WAF. For a
  public internet-facing instance, put it behind a CDN/WAF and add per-API-key quotas.

## Verified on

`deploy/` was authored and reviewed here, but this sandbox has **no Docker, no
Podman, no nginx and no gunicorn**, so those files could not be executed here.
What *was* executed and is documented in [`../VERIFY.md`](../VERIFY.md): the
production uvicorn profile (2 workers, `ENVIRONMENT=production`), the 12/12 smoke
test, the load test, and the full 238-test suite. Run `prod_smoke_test.py` after
your first real deployment — that is what it is for.
