# SKF Racing Hub – Python Backend

FastAPI backend for the SKF Racing Hub, deployed on Railway with PostgreSQL.

## Local Development

```bash
cd backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Copy env and configure
cp .env.example .env
# Edit .env with your DATABASE_URL and SIMGRID_API_KEY

# Run migrations
alembic upgrade head

# Start dev server
uvicorn app.main:app --reload --port 8000
```

## Railway Setup

1. Add a **PostgreSQL** database in your Railway project
2. Create a new service from your repo, set **Root Directory** to `skf-site/backend`
3. Railway auto-injects `DATABASE_URL` from the linked PostgreSQL service
4. Add `SIMGRID_API_KEY`, `CORS_ORIGINS` and `FRONTEND_URL` (the public origin of the site; Discord login redirects there and an `https` URL makes the session cookie `Secure`) as environment variables
5. Add a **Bucket** to the project and connect it to the backend service with **Add to Service** (the default `AWS_*` variable names work; `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_REGION` are accepted too). Uploaded race-result files are kept there; without these variables imports still work but the originals are not stored
6. The start command in `railway.toml` runs migrations automatically on deploy; the migrations create the whole schema. On startup the app syncs translations with `seed/translations_*.json`: missing keys are added, keys no longer in the files are removed, and values edited in the admin UI are kept

## API

Everything lives under **`/api/v1`**; the interactive reference is at `/docs`.

- JSON bodies, responses and multi-word query parameters are camelCase; ids are UUIDs (SimGrid ids are integers).
- Errors are `application/problem+json`: `{type, title, status, detail, code}`; validation errors add `errors: [{field, message}]`.
- Creates answer `201` with a `Location` header; bodiless answers are `204`.
- Growing collections take `?limit=` (default 100, max 1000) and `?offset=`, and return the total in `X-Total-Count` plus `Link` to neighbouring pages.
- Auth is the `session_id` cookie set by the Discord login. "judge" means racing judge or admin; "CM" is a community manager.

### Session and account
- `GET /auth/discord/authorization-url` – Discord login URL (sets the OAuth state cookie)
- `DELETE /auth/session` – log out
- `GET /me` – current user, `401` when anonymous
- `POST /me/discord-syncs` – re-read the Discord server nickname
- `GET|PATCH /me/driver` – the driver linked to me; PATCH sets `photoUrl` (https only)

### Users and maintenance (admin)
- `GET /users`, `PATCH /users/{id}` (role, blocked), `DELETE /users/{id}/sessions`
- `GET|PUT /users/{id}/managed-communities`
- `DELETE /caches`, `DELETE /caches/{simgrid|youtube}`

### Drivers and BWP
- `GET /drivers` (`?simgridId=`, `?include=account` for judges), `GET /drivers/{id}`
- `POST /drivers` (admin), `PATCH /drivers/{id}` (judge), `DELETE /drivers/{id}` (admin)
- `POST /drivers/{id}/bwp-points`, `PATCH /bwp-points/{id}` (`{expired: true, note}`), `DELETE /bwp-points/{id}`
- `POST /drivers/{id}/bwp-resets` – expire every point and clear the clearances
- `PUT|DELETE /drivers/{id}/clearances/{ruleId}`
- `GET|POST /penalty-rules`, `PATCH|DELETE /penalty-rules/{id}`

### Championships (SimGrid proxy)
- `GET /championships`, `/championships/{id}`, `/{id}/standings`, `/{id}/races`, `/{id}/incident-windows`
- `GET /championships/{id}/races/{raceId}/results?session=race|qualifying` – one race's classification; `/{id}/standings` entries carry per-round `raceResults`
- `GET /active-championships`, `PUT|DELETE /active-championships/{simgridId}` (admin)
- `GET /championships/{id}/rounds` – rounds with their upload and incident window (admin)
- `GET /championships/{id}/giveaway-eligibility?minDistancePct=&minRounds=` and `/{id}/unmatched-driver-names` (admin)
- `GET|POST /driver-aliases`, `GET|DELETE /driver-aliases/{id}` (admin; POST upserts by alias)

### Race results (admin)
One game-server result file per SimGrid round: `.xml` for Le Mans Ultimate, iRaceControl `.bin` for iRacing (picked from the championship's game). It feeds the giveaway and the round's Auto incidents.
- `GET /race-result-imports?championshipId=`, `GET /race-result-imports/{id}`
- `POST /race-result-imports` – multipart `file`, `championshipId`, `raceId`, optional `createIncidents`, `windowHours`
- `GET /race-result-imports/{id}/file` – the stored original
- `POST /race-result-imports/{id}/parse-runs` – re-run the parser on the stored original
- `DELETE /race-result-imports/{id}` – remove the results (incidents stay)

### Incidents
- `GET|POST /incident-windows`, `GET|PATCH|DELETE /incident-windows/{id}`
- `POST /incident-windows/{id}/incidents` – file an incident (anonymous allowed, rate limited)
- `PATCH /incident-windows/{id}/incidents` (`{isPublished: true}`) – publish the window and issue BWP
- `POST /incident-windows/{id}/default-resolutions` – apply the default verdict to every unresolved driver
- `POST /incidents/{id}/copies`, `POST /incidents/{id}/drivers`, `PUT /incidents/{id}/resolution`
- `PATCH|DELETE /incident-drivers/{id}`, `PUT /incident-drivers/{id}/resolution`
- `GET|POST /verdict-rules`, `PUT /verdict-rules/order`, `PATCH|DELETE /verdict-rules/{id}`
- `GET|POST /description-presets`, `PATCH|DELETE /description-presets/{id}`
- `GET /bwp-audit-entries`, `POST /bwp-backfills` (admin)

### Calendar and communities
- `GET /calendar-events?year=&month=`, `GET /simulators`, `GET /car-classes?gameId=`
- `GET /communities` (`?scope=managed` for admins and CMs), `POST` (admin), `PATCH|DELETE /communities/{id}`
- `POST /community-requests` – forwarded to Discord
- `GET|POST /custom-championships` (`?communityId=`), `GET|PATCH|DELETE /custom-championships/{id}`
- `POST|PUT /custom-championships/{id}/races`, `PATCH|DELETE /custom-championships/{id}/races/{raceId}`

### Content
- `GET /regulations?lang=`, `GET /regulations/{slug}?lang=`
- `GET|POST /regulation-pages`, `GET|PATCH|DELETE /regulation-pages/{id}` (admin)
- `GET|POST /languages`, `DELETE /languages/{code}`
- `GET /languages/{code}/translations` – flat `{key: value}` map (`?prefix=`, `?download=true`)
- `PATCH /languages/{code}/translations` – merge a map (admin), `DELETE /languages/{code}/translations/{key}`
- `GET /youtube-streams?status=past|upcoming&limit=`

### Fixed pre-v1 paths
Two endpoints keep their old address because an outside party is tied to it:
- `GET /api/auth/discord/callback` – the redirect URI registered with Discord
- `POST /api/incidents/ingest` – **deprecated** batch ingest for the desktop parsers (`Authorization: Bearer <INCIDENT_API_TOKEN>`); responses carry `Deprecation: true`. Use race-result uploads instead
