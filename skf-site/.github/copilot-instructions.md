# GitHub Copilot Instructions — SKF Racing Hub

## Project Overview

Full-stack sim-racing club management app for SKF Racing Hub.

- **Frontend**: Angular 21, standalone components, signals, zoneless change detection
- **Backend**: FastAPI + SQLAlchemy (async), PostgreSQL + asyncpg (production), SQLite + aiosqlite (tests)
- **Auth**: Discord OAuth2 with JWT sessions
- **External API**: SimGrid (race results, championship standings, driver data)

## Repository Structure

```
src/                        # Angular frontend
  app/
    pages/                  # Route-level components
    services/               # Angular services
    guards/                 # Route guards
    interceptors/           # HTTP interceptors
backend/
  app/
    routers/                # FastAPI route handlers
    models/                 # SQLAlchemy ORM models
    schemas/                # Pydantic request/response schemas
    services/               # Business logic
  tests/                    # pytest test suite
```

## Development Workflow — TDD Required

**Always follow Test-Driven Development:**

1. **Write tests first** before implementing any new feature or fix.
2. Run the tests to confirm they fail (red).
3. Implement the minimum code to make them pass (green).
4. Refactor if needed, keeping all tests green.
5. **Double-check the solution** — review for edge cases, security issues, and correctness before finishing.
6. **Run all tests after every implementation** to ensure nothing is broken.

## Running Tests

### Frontend (vitest)
```bash
npm test
# or in watch mode:
npm run test:watch
```

Test files live alongside components as `*.spec.ts`.

### Backend (pytest)
```bash
# From the backend/ directory, using the test virtualenv:
cd backend
.venv-test\Scripts\activate      # Windows
pytest tests/ -v
```

Test files live in `backend/tests/`. The conftest sets `DATABASE_URL` to an in-memory SQLite DB before any app import — always respect this pattern in new fixtures.

## Code Conventions

### Angular
- Use **standalone components** with `imports: [...]` — no NgModules.
- Use Angular **signals** (`signal()`, `computed()`) for state; avoid RxJS Subject for local state.
- Use `@for`, `@if`, `@else` control flow syntax (not `*ngFor`, `*ngIf`).
- Services are `providedIn: 'root'` singletons injected with `inject()`.
- HTTP calls go through dedicated service classes in `src/app/services/`.
- snake_case from the API is automatically camelCased by the backend's `CamelModel`.

### FastAPI / Backend
- All response schemas extend `CamelModel` (auto camelCase serialization) unless the client explicitly expects snake_case.
- Register new routes **before** parameterized routes (e.g. `/driver/results` before `/{id}`) to avoid shadowing.
- Use `Depends(get_db)` for DB sessions in route handlers; never create sessions manually.
- Auth-protected routes use `Depends(require_auth)`.
- Background tasks (e.g. cache warming) use `BackgroundTasks`.

### Database / Alembic
- All schema changes go through Alembic migrations in `backend/alembic/versions/`.
- Never modify existing migration files; always create a new revision.

## Security
- Never expose raw database IDs or internal tokens in API responses unless required.
- Validate all user-supplied input at the API boundary (Pydantic schemas enforce this).
- OAuth scopes: only request the minimum necessary Discord scopes.
- All auth state is stored server-side in the `sessions` table; the client only holds an opaque session token (HttpOnly cookie or Bearer token).
