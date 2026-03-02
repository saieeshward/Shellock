"""Module discovery and loading.

Discovers installed Shellock modules from two sources:
    1. Built-in modules (shellock.modules.*)
    2. Entry points (shellock.modules group in pyproject.toml)

Modules are lazy-loaded — only instantiated when needed.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from shellock_core.module_base import ShellockModule

logger = logging.getLogger(__name__)

# Cache loaded modules
_module_cache: dict[str, ShellockModule] = {}

# Built-in module names
BUILTIN_MODULES = ["python", "node"]


def discover_modules() -> list[str]:
    """Return a list of all available module names."""
    names = list(BUILTIN_MODULES)

    # Check entry points for third-party modules
    try:
        from importlib.metadata import entry_points

        eps = entry_points()
        if hasattr(eps, "select"):
            shellock_eps = eps.select(group="shellock.modules")
        else:
            shellock_eps = eps.get("shellock.modules", [])

        for ep in shellock_eps:
            if ep.name not in names:
                names.append(ep.name)
    except Exception as e:
        logger.debug("Could not load entry points: %s", e)

    return names


def load_module(name: str) -> ShellockModule | None:
    """Load and instantiate a module by name. Returns None if not found."""
    if name in _module_cache:
        return _module_cache[name]

    # Try built-in modules first
    if name in BUILTIN_MODULES:
        try:
            mod = importlib.import_module(f"shellock_core.modules.{name}")
            instance = mod.Module()
            _module_cache[name] = instance
            return instance
        except (ImportError, AttributeError) as e:
            logger.error("Failed to load built-in module '%s': %s", name, e)
            return None

    # Try entry points
    try:
        from importlib.metadata import entry_points

        eps = entry_points()
        if hasattr(eps, "select"):
            shellock_eps = eps.select(group="shellock.modules")
        else:
            shellock_eps = eps.get("shellock.modules", [])

        for ep in shellock_eps:
            if ep.name == name:
                cls = ep.load()
                instance = cls()
                _module_cache[name] = instance
                return instance
    except Exception as e:
        logger.debug("Could not load entry point module '%s': %s", name, e)

    return None


def detect_modules(project_path: str) -> list[ShellockModule]:
    """Auto-detect which modules apply to the given project.

    Checks each available module's ``detect()`` method against
    the project directory.
    """
    matches = []
    for name in discover_modules():
        module = load_module(name)
        if module and module.detect(project_path):
            matches.append(module)
            logger.info("Detected module: %s", name)
    return matches


def get_module(name: str) -> ShellockModule:
    """Load a module by name, raising ValueError if not found."""
    module = load_module(name)
    if module is None:
        available = discover_modules()
        raise ValueError(
            f"Module '{name}' not found. Available modules: {', '.join(available)}"
        )
    return module
