"""Pre-v1 routers still being migrated to ``app.api.v1`` (temporary)."""

import importlib
import pkgutil

ROUTERS = [
    importlib.import_module(f"{__name__}.{m.name}").router
    for m in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name)
]
