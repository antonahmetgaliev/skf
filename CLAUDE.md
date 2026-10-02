# SKF Racing Hub

Sim-racing club site: championships and standings (from SimGrid), a race calendar for several communities, driver licence points (BWP), an incident/judging workflow and a giveaway fed by uploaded race-result files. Maintained by one developer.

## Layout
- `frontend/` — Angular 21 app (standalone components, signals, zoneless). Served in prod by `server.js` (Express), which proxies `/api` to the backend.
- `backend/` — FastAPI + async SQLAlchemy + Alembic, Postgres in prod.
- `openapi.json` — the API contract between them: exported from the backend, frontend types are generated from it.
- `docs/features.md` — what each feature consists of and how features affect each other. Start here.
- `docs/deploy.md` — Railway services, env vars, migrations, rollback.
- `docs/simgrid.md` — verified behaviour of the external SimGrid API.
- `design/` — source images (community logos, broadcast overlays, photos). Not used by the site; the site's own images are in `frontend/public/`.

## Environment
There is **one** environment: production on Railway. No local backend, no local database, no `.env`.
- Backend changes are verified by tests and CI only. Never create a `.env` with prod credentials or run the backend, migrations or seeds locally.
- `npm run dev` serves the frontend and proxies `/api` to the **production** backend: actions in the dev UI change real data.
- Pushing to `main` deploys both services; Railway waits for CI.

## Commands
Backend (`cd backend`, venv in `.venv`, `pip install -r requirements-dev.txt`):
- `.venv/bin/pytest` — tests on in-memory SQLite, no env needed
- `.venv/bin/ruff check . && .venv/bin/ruff format .`

Frontend (`cd frontend`):
- `npm run dev` · `npm test` · `npm run lint` · `npm run format` · `npm run build`

After any change to a backend schema or route, refresh the API contract: run `python -m scripts.export_openapi` in `backend/`, then `npm run api:types` in `frontend/`. Commit `openapi.json` and `frontend/src/app/api-schema.d.ts` with the change.

CI (`.github/workflows/ci.yml`) runs all of the above. It also runs `alembic upgrade head` and `alembic check` on a throwaway Postgres, and fails if `openapi.json` or the generated types are out of date.

## Backend conventions
- Routers in `app/api/v1/` are auto-discovered and stay thin: parse input, call a service, return a schema. Business logic and commits live in `app/services/`.
- Resources: a collection answers the same for every caller; what only some may see is asked for explicitly (`?include=inactive`, guarded by `ensure_admin`), never switched on by role. Every `201` sets `Location`, and that path has a `GET`. A state that belongs to a resource is a field on it (`PATCH /championships/{id}` with `isActive`), not a separate collection; a one-way action is a sub-resource (`PUT /incident-windows/{id}/publication`).
- Errors: raise `AppError` subclasses from `app/core/errors.py` (rendered as `application/problem+json`), never `HTTPException`. `repository.get_or_404` for lookups.
- OpenAPI: `app/core/openapi.py` derives what it can from the routes (401/403 from the auth dependency, 404 from path params, 422, paging and `Location` headers). A route declares only its own extra errors: `responses=problem_responses(409)`. The handler's name becomes its `operationId`, so it must be unique API-wide and say what it does (`list_incident_windows`, not `list_windows`). `tests/test_openapi_contract.py` enforces the rules.
- Schemas extend the camelCase base in `app/schemas/base.py`; the API speaks camelCase, Python stays snake_case. The same module has the shared field types: in a PATCH body a field that cannot be cleared is `Omittable[T] = None` (absent keeps the value, `null` is a 422) and only a clearable one is `T | None = None`; upstream date strings are `IsoDateTime`, response URLs `Url`. A closed set of values is a `StrEnum` in `app/schemas/enums.py`, not a `Literal` or a bare `str`.
- Names: a response schema ends in `Out` (`XSummaryOut` for a list row), a request body in `Create`, `Update` or `Upsert`. One thing has one name everywhere: `championshipId` and `raceId` are SimGrid's ids, with no `simgrid` infix. Path parameters are camelCase too — take their types from `app/api/params.py` (`driver_id: DriverId` for `/drivers/{driverId}`).
- Auth: `session_id` cookie from Discord login, sessions in the DB. Use `get_current_user` / `require_role(...)` from `app/auth.py`. Roles: `driver`, `moderator`, `racing_judge`, `community_manager`, `admin`, `super_admin` (`app/models/user.py`).
- Schema changes need a new Alembic revision in `alembic/versions/`; never edit an applied one. CI fails if models and migrations drift.
- Two pre-v1 paths are fixed by outside parties: `GET /api/auth/discord/callback` and the deprecated `POST /api/incidents/ingest`.

## Frontend conventions
- One folder per component (`.ts/.html/.scss`), `app-` prefix, signal `input()`/`output()`, `@if`/`@for` control flow.
- API calls go through `src/app/services/*-api.service.ts`; base path is `API` from `src/app/api.ts`.
- API types are generated, never hand-written: `export type Foo = Schemas['FooOut']` (`Schemas` from `src/app/api.ts`). If a type is wrong, fix the Pydantic schema, not the alias.
- New or reworked components use `ChangeDetectionStrategy.OnPush`, and subscriptions end with `takeUntilDestroyed()`. Don't mass-migrate old components; convert them when you touch them anyway.
- Pure logic (date maths, grouping, summaries) goes into a plain `.ts` module next to the page, with a `.spec.ts` (see `pages/calendar/calendar-events.ts`). Components keep state and wiring.
- UI strings go through Transloco. Keys live in `backend/seed/translations_{en,ua}.json`.

## Things that are not obvious from the code
- Every backend start runs migrations (`app.migrate`), then `app/seed.py`. The seed syncs translations with the seed JSON files: missing keys are added, and **keys missing from the files are deleted**. Values edited in the admin UI are kept.
- SimGrid responses are cached in the `simgrid_cache` table. When SimGrid fails, stale data is served and the `X-Data-Stale` header is set.
- Raw race-result exports can contain private in-race chat. The root `.gitignore` blocks LMU exports by their filename pattern. Commit only scrubbed fixtures to `backend/tests/fixtures/`.

## Keeping docs alive
Docs only record *where* things are and *why*. Never copy what code or `/docs` (OpenAPI) already say: no endpoint lists, no field lists. When a change adds, renames or removes a feature, command or env var, update the matching line in this file or `docs/` in the same commit. A doc that can't be kept current gets deleted.
