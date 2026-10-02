"""Write the API's OpenAPI spec to openapi.json at the repo root.

Run from backend/: python -m scripts.export_openapi
The frontend generates its API types from that file (npm run api:types).
"""

import json
from pathlib import Path

from app.main import app

OUT = Path(__file__).resolve().parents[2] / "openapi.json"

if __name__ == "__main__":
    OUT.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {OUT}")
