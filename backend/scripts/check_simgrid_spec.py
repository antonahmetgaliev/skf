"""Compare SimGrid's live OpenAPI spec with our pinned copy.

Exits 1 and prints a unified diff when the spec changed, so a silent contract
change (like the 2026-09-28 switch to wrapped collections) is noticed before
it breaks the site. Downloads the public spec only; no API token is used.

Usage: python scripts/check_simgrid_spec.py [--update]
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

import httpx

SPEC_URL = "https://gridos.thesimgrid.com/openapi.yml"
PINNED = Path(__file__).resolve().parent.parent / "simgrid" / "openapi.yml"


def main() -> int:
    live = httpx.get(SPEC_URL, timeout=30.0, follow_redirects=True)
    live.raise_for_status()
    pinned = PINNED.read_text(encoding="utf-8")

    if live.text == pinned:
        print("SimGrid spec unchanged.")
        return 0

    if "--update" in sys.argv:
        PINNED.write_text(live.text, encoding="utf-8")
        print(f"Pinned spec updated: {PINNED}")
        return 0

    sys.stdout.writelines(
        difflib.unified_diff(
            pinned.splitlines(keepends=True),
            live.text.splitlines(keepends=True),
            fromfile="pinned/openapi.yml",
            tofile="live/openapi.yml",
        )
    )
    print("\nSimGrid spec changed. Review, adapt app/services/simgrid.py, then rerun with --update.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
