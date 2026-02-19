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
4. Add `SIMGRID_API_KEY` and `CORS_ORIGINS` as environment variables
5. The start command in `railway.toml` runs migrations automatically on deploy

## API Endpoints

### BWP License
- `GET    /api/bwp/drivers` – list all drivers with points
- `POST   /api/bwp/drivers` – create driver `{ "name": "..." }`
- `DELETE /api/bwp/drivers/{id}` – delete driver
- `POST   /api/bwp/drivers/{id}/points` – add penalty point
- `DELETE /api/bwp/points/{id}` – delete point
- `GET    /api/bwp/penalty-rules` – list penalty rules
- `POST   /api/bwp/penalty-rules` – create rule
- `PATCH  /api/bwp/penalty-rules/{id}` – update rule
- `DELETE /api/bwp/penalty-rules/{id}` – delete rule

### Championships (SimGrid proxy)
- `GET /api/championships` – list championships
- `GET /api/championships/{id}` – championship details
- `GET /api/championships/{id}/standings` – standings with race positions
