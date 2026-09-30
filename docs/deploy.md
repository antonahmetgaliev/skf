# Deploy

Everything runs on Railway, which deploys on every push to `main` (Railpack builder), after CI passes ("Wait for CI").

## Services
| Service | Root directory | Start | Health check |
|---|---|---|---|
| backend | `skf-site/backend` | `railway.toml`: `python -m app.migrate && uvicorn app.main:app` | `/healthz` |
| frontend | `skf-site` | `npm start` → `server.js` (serves `dist/`, proxies `/api` to the backend) | `/healthz` |
| Postgres | — | Railway plugin; injects `DATABASE_URL` into the backend | — |
| Bucket | — | Railway S3-compatible bucket linked to the backend with "Add to Service" | — |

Versions: Python from `backend/.python-version`, Node from `skf-site/.nvmrc`.

## Environment variables
Values live only in Railway. Defaults are in `backend/app/config.py`.

Backend:
- `DATABASE_URL` — injected by the Postgres plugin.
- `FRONTEND_URL` — public site origin. Discord login redirects here, and an `https` URL makes the session cookie `Secure`. `CORS_ORIGINS` — allowed origins.
- `SIMGRID_API_KEY` — SimGrid API.
- `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI` — Discord login.
- `DISCORD_GUILD_ID`, `DISCORD_BOT_TOKEN` — read server nicknames for driver matching.
- `DISCORD_COMMUNITY_REQUEST_WEBHOOK_URL` — where community requests from the calendar go.
- `SUPER_ADMIN_DISCORD_ID` — gets `super_admin` on first login.
- `YOUTUBE_API_KEY`, `YOUTUBE_CHANNEL_ID` — media page.
- `INCIDENT_API_TOKEN` — bearer token for the deprecated incident ingest endpoint.
- `AWS_*` / `S3_*` — bucket for original race-result files. They are optional: without them uploads still work, but the originals aren't stored.
- `SESSION_MAX_AGE_HOURS` — optional, defaults to a week.

Frontend:
- `BACKEND_URL` — the backend's Railway URL (the proxy target).
- `GA_MEASUREMENT_ID` — optional GA4; served to the browser via `/env.js`.

## Migrations
- They run on every backend start. If a migration fails, the process exits and Railway keeps the previous deployment serving.
- CI checks every push: it applies all migrations to an empty Postgres and runs `alembic check`, which fails if the models changed without a migration.
- Migrations only go forward. To undo one, write a new revision.

## When a deploy goes wrong
1. Railway → service → Deployments → pick the last good deployment → **Redeploy**. Code rolls back in about a minute.
2. The database does **not** roll back with code. If the bad deploy ran a migration, the old code has to work with the new schema. This is why a migration should only add things (columns, tables); removals go in a later release.
3. Then fix forward on `main`.
4. Data restore: Railway → Postgres → Backups. Check that backups are enabled.
