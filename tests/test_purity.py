"""The core package must not import homeassistant — ever.

This test poisons ``homeassistant`` in ``sys.modules`` and then imports
every module under ``custom_components.grow_conductor.core``. Any HA
import inside the core raises immediately.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys

import pytest

CORE_PACKAGE = "custom_components.grow_conductor.core"


class _PoisonedModule:
    def __getattr__(self, name: str):  # pragma: no cover
        raise AssertionError("core/ must not touch homeassistant")


def test_core_is_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    # Evict anything already imported, then poison homeassistant.
    for name in list(sys.modules):
        if name.startswith((CORE_PACKAGE, "homeassistant")):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "homeassistant", _PoisonedModule())

    package = importlib.import_module(CORE_PACKAGE)
    for module_info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{CORE_PACKAGE}.{module_info.name}")
        for attr in vars(module).values():
            assert not getattr(attr, "__module__", "").startswith("homeassistant"), (
                f"{module.__name__} leaked a homeassistant symbol: {attr!r}"
            )
