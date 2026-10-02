"""Run Alembic migrations at startup.

Called from railway.toml start command:
    python -m app.migrate && uvicorn ...

If migration fails the process exits non-zero so Railway retries.
"""

import logging
import subprocess
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.migrate")


def main() -> None:
    logger.info("Running alembic upgrade head ...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        logger.info(result.stdout.strip())
    if result.stderr:
        logger.warning(result.stderr.strip())
    if result.returncode != 0:
        logger.error(f"Alembic migration failed with code {result.returncode}")
        sys.exit(result.returncode)
    logger.info("Migrations complete")


if __name__ == "__main__":
    main()
