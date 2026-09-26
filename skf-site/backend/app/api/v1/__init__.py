"""Version 1 of the public API, mounted under ``/api/v1``.

Every module in this package that defines ``router`` is included here. A
module may also define ``legacy_router`` for the few endpoints that must keep
their pre-v1 path under ``/api`` because an outside party is tied to it (the
Discord OAuth redirect URI, the external incident ingest client).
"""

import importlib
import pkgutil

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")
legacy_router = APIRouter(prefix="/api")

for _module in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
    _mod = importlib.import_module(f"{__name__}.{_module.name}")
    if hasattr(_mod, "router"):
        router.include_router(_mod.router)
    if hasattr(_mod, "legacy_router"):
        legacy_router.include_router(_mod.legacy_router)
