"""Dynamic package knowledge base.

Provides on-demand lookup of package metadata from PyPI and npm,
with a local JSON cache (~/.shellock/knowledge/packages.json).

Network is only hit when:
  1. A package is not in the local cache, OR
  2. The cached entry is older than CACHE_TTL_DAYS (7 days)

All network calls use stdlib urllib with a 3-second timeout and
degrade silently to the static IMPORT_TO_PYPI fallback if offline.
No additional dependencies required.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PYPI_API = "https://pypi.org/pypi/{package}/json"
NPM_API = "https://registry.npmjs.org/{package}"
CACHE_TTL_DAYS = 7
FETCH_TIMEOUT = 3  # seconds


class PackageKnowledgeManager:
    """Cache-first package metadata manager.

    Looks up package metadata from PyPI / npm and stores results in a
    local JSON cache so repeated lookups are instant and work offline.
    """

    def __init__(self, cache_path: Path) -> None:
        self.cache_path = cache_path
        self._cache: dict[str, Any] = self._load_cache()

    # ── Cache I/O ────────────────────────────────────────────────

    def _load_cache(self) -> dict[str, Any]:
        if self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text())
            except Exception as e:
                logger.debug("Could not load knowledge cache: %s", e)
        return {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, indent=2, default=str) + "\n"
        )

    def _is_stale(self, entry: dict[str, Any]) -> bool:
        fetched_at = entry.get("fetched_at")
        if not fetched_at:
            return True
        try:
            age = datetime.now() - datetime.fromisoformat(fetched_at)
            return age > timedelta(days=CACHE_TTL_DAYS)
        except Exception:
            return True

    # ── Network fetches ──────────────────────────────────────────

    def fetch_pypi(self, package_name: str) -> dict[str, Any] | None:
        """Fetch package metadata from the PyPI JSON API.

        Returns a metadata dict on success, None on any network/parse error.
        """
        try:
            import urllib.request

            url = PYPI_API.format(package=package_name)
            with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as resp:
                data = json.loads(resp.read())
            info = data.get("info", {})
            return {
                "name": info.get("name", package_name),
                "summary": info.get("summary", ""),
                "home_page": info.get("home_page", ""),
                "exists": True,
                "ecosystem": "pypi",
                "fetched_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.debug("PyPI fetch failed for '%s': %s", package_name, e)
            return None

    def fetch_npm(self, package_name: str) -> dict[str, Any] | None:
        """Fetch package metadata from the npm registry.

        Returns a metadata dict on success, None on any network/parse error.
        """
        try:
            import urllib.request

            url = NPM_API.format(package=package_name)
            with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as resp:
                data = json.loads(resp.read())
            return {
                "name": data.get("name", package_name),
                "summary": data.get("description", ""),
                "home_page": data.get("homepage", ""),
                "exists": True,
                "ecosystem": "npm",
                "fetched_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.debug("npm fetch failed for '%s': %s", package_name, e)
            return None

    # ── Public API ───────────────────────────────────────────────

    def get_or_fetch(
        self, package_name: str, ecosystem: str = "pypi"
    ) -> dict[str, Any] | None:
        """Return cached metadata, fetching from the registry if missing or stale.

        Returns None when offline or package does not exist.
        """
        cache_key = f"{ecosystem}:{package_name.lower()}"
        entry = self._cache.get(cache_key)
        if entry and not self._is_stale(entry):
            return entry

        if ecosystem == "pypi":
            fresh = self.fetch_pypi(package_name)
        elif ecosystem == "npm":
            fresh = self.fetch_npm(package_name)
        else:
            return None

        if fresh:
            self._cache[cache_key] = fresh
            self._save_cache()

        return fresh

    def verify_and_enrich(
        self, spec_dict: dict[str, Any], ecosystem: str = "pypi"
    ) -> tuple[dict[str, Any], list[str]]:
        """Validate package names in a spec and fix common aliases.

        Resolution order per package:
          1. Static IMPORT_TO_PYPI map — works fully offline (e.g. sklearn → scikit-learn)
          2. Live registry lookup — corrects casing and confirms existence

        Non-blocking: unresolvable packages are left unchanged.

        Returns:
            (updated_spec_dict, list_of_changes) where each change is a
            human-readable string describing what was corrected.
        """
        from shellock_core.core.import_scanner import IMPORT_TO_PYPI

        packages = spec_dict.get("packages", [])
        updated: list[dict[str, Any]] = []
        changes: list[str] = []

        for pkg in packages:
            name = pkg.get("name") if isinstance(pkg, dict) else str(pkg)
            if not name:
                updated.append(pkg)
                continue

            # Step 1: static alias map (instant, offline)
            canonical = IMPORT_TO_PYPI.get(name)
            if canonical and canonical.lower() != name.lower():
                changes.append(f"{name} → {canonical} (alias)")
                entry = dict(pkg) if isinstance(pkg, dict) else {"name": name}
                entry["name"] = canonical
                updated.append(entry)
                logger.info("Alias resolved (static): %s → %s", name, canonical)
                continue

            # Step 2: live registry lookup for canonical casing / existence check
            meta = self.get_or_fetch(name, ecosystem)
            if meta and meta.get("exists"):
                canonical_name = meta.get("name", name)
                if canonical_name != name:
                    changes.append(f"{name} → {canonical_name} (registry)")
                    entry = dict(pkg) if isinstance(pkg, dict) else {"name": name}
                    entry["name"] = canonical_name
                    updated.append(entry)
                    logger.info(
                        "Canonical name from registry: %s → %s", name, canonical_name
                    )
                else:
                    updated.append(pkg)
            else:
                # Offline or not found — leave unchanged
                updated.append(pkg)

        spec_dict = dict(spec_dict)
        spec_dict["packages"] = updated
        return spec_dict, changes

    def refresh_stale(self, ecosystem: str | None = None) -> int:
        """Re-fetch all stale entries. Returns count of refreshed entries."""
        refreshed = 0
        for key, entry in list(self._cache.items()):
            eco, _, pkg_name = key.partition(":")
            if ecosystem and eco != ecosystem:
                continue
            if not self._is_stale(entry):
                continue
            fetch_fn = self.fetch_pypi if eco == "pypi" else self.fetch_npm
            fresh = fetch_fn(pkg_name)
            if fresh:
                self._cache[key] = fresh
                refreshed += 1
        if refreshed:
            self._save_cache()
        return refreshed

    def cache_stats(self) -> dict[str, Any]:
        """Return counts of cached entries and how many are stale."""
        total = len(self._cache)
        stale = sum(1 for e in self._cache.values() if self._is_stale(e))
        by_ecosystem: dict[str, int] = {}
        for key in self._cache:
            eco = key.split(":")[0]
            by_ecosystem[eco] = by_ecosystem.get(eco, 0) + 1
        return {"total": total, "stale": stale, "by_ecosystem": by_ecosystem}


def get_knowledge_manager() -> PackageKnowledgeManager:
    """Return a knowledge manager backed by the standard cache path."""
    from shellock_core.core.registry import SHELLOCK_HOME

    cache_path = SHELLOCK_HOME / "knowledge" / "packages.json"
    return PackageKnowledgeManager(cache_path)
