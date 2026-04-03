"""Tests for the dynamic package knowledge base."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shellock_core.core.knowledge import PackageKnowledgeManager, CACHE_TTL_DAYS


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    return tmp_path / "packages.json"


@pytest.fixture
def km(cache_path: Path) -> PackageKnowledgeManager:
    return PackageKnowledgeManager(cache_path)


# ── Helpers ───────────────────────────────────────────────────────


def _pypi_response(name: str, summary: str = "") -> dict:
    """Build a minimal PyPI JSON API response."""
    return {
        "info": {
            "name": name,
            "summary": summary,
            "home_page": f"https://pypi.org/project/{name}",
        }
    }


def _npm_response(name: str, description: str = "") -> dict:
    return {"name": name, "description": description, "homepage": ""}


# ── Cache I/O ────────────────────────────────────────────────────


class TestCacheIO:

    def test_empty_cache_on_missing_file(self, cache_path):
        km = PackageKnowledgeManager(cache_path)
        assert km._cache == {}

    def test_loads_existing_cache(self, tmp_path):
        cache_path = tmp_path / "packages.json"
        cache_path.write_text(json.dumps({"pypi:fastapi": {"name": "fastapi", "exists": True}}))
        km = PackageKnowledgeManager(cache_path)
        assert "pypi:fastapi" in km._cache

    def test_save_creates_parent_dirs(self, tmp_path):
        cache_path = tmp_path / "a" / "b" / "packages.json"
        km = PackageKnowledgeManager(cache_path)
        km._cache["pypi:x"] = {"name": "x", "exists": True}
        km._save_cache()
        assert cache_path.exists()

    def test_corrupted_cache_file_loads_empty(self, tmp_path):
        cache_path = tmp_path / "packages.json"
        cache_path.write_text("{bad json!!!")
        km = PackageKnowledgeManager(cache_path)
        assert km._cache == {}


# ── Staleness ────────────────────────────────────────────────────


class TestStaleness:

    def test_missing_fetched_at_is_stale(self, km):
        assert km._is_stale({}) is True

    def test_fresh_entry_not_stale(self, km):
        from datetime import datetime
        entry = {"fetched_at": datetime.now().isoformat()}
        assert km._is_stale(entry) is False

    def test_old_entry_is_stale(self, km):
        from datetime import datetime, timedelta
        old = datetime.now() - timedelta(days=CACHE_TTL_DAYS + 1)
        entry = {"fetched_at": old.isoformat()}
        assert km._is_stale(entry) is True

    def test_entry_exactly_at_ttl_is_stale(self, km):
        from datetime import datetime, timedelta
        exactly = datetime.now() - timedelta(days=CACHE_TTL_DAYS)
        entry = {"fetched_at": exactly.isoformat()}
        assert km._is_stale(entry) is True


# ── fetch_pypi ───────────────────────────────────────────────────


class TestFetchPyPI:

    def test_returns_metadata_on_success(self, km):
        response_data = json.dumps(_pypi_response("fastapi", "FastAPI framework")).encode()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = response_data

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = km.fetch_pypi("fastapi")

        assert result is not None
        assert result["name"] == "fastapi"
        assert result["exists"] is True
        assert result["ecosystem"] == "pypi"
        assert "fetched_at" in result

    def test_returns_none_on_network_error(self, km):
        with patch("urllib.request.urlopen", side_effect=OSError("no network")):
            result = km.fetch_pypi("nonexistent-xyz")
        assert result is None

    def test_canonical_name_preserved(self, km):
        """PyPI returns canonical casing — 'fastapi' stays 'fastapi'."""
        response_data = json.dumps(_pypi_response("FastAPI")).encode()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = response_data

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = km.fetch_pypi("fastapi")

        assert result["name"] == "FastAPI"


# ── fetch_npm ────────────────────────────────────────────────────


class TestFetchNpm:

    def test_returns_metadata_on_success(self, km):
        response_data = json.dumps(_npm_response("react", "React library")).encode()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = response_data

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = km.fetch_npm("react")

        assert result is not None
        assert result["name"] == "react"
        assert result["exists"] is True
        assert result["ecosystem"] == "npm"

    def test_returns_none_on_network_error(self, km):
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            result = km.fetch_npm("react")
        assert result is None


# ── get_or_fetch ─────────────────────────────────────────────────


class TestGetOrFetch:

    def test_returns_cached_entry_without_network(self, km):
        from datetime import datetime
        km._cache["pypi:fastapi"] = {
            "name": "fastapi",
            "exists": True,
            "fetched_at": datetime.now().isoformat(),
        }
        with patch.object(km, "fetch_pypi") as mock_fetch:
            result = km.get_or_fetch("fastapi", "pypi")
        mock_fetch.assert_not_called()
        assert result["name"] == "fastapi"

    def test_fetches_when_not_cached(self, km):
        meta = {"name": "fastapi", "exists": True, "fetched_at": "2099-01-01T00:00:00"}
        with patch.object(km, "fetch_pypi", return_value=meta) as mock_fetch:
            result = km.get_or_fetch("fastapi", "pypi")
        mock_fetch.assert_called_once_with("fastapi")
        assert result is meta

    def test_fetches_when_stale(self, km):
        from datetime import datetime, timedelta
        km._cache["pypi:fastapi"] = {
            "name": "fastapi",
            "exists": True,
            "fetched_at": (datetime.now() - timedelta(days=30)).isoformat(),
        }
        meta = {"name": "fastapi", "exists": True, "fetched_at": "2099-01-01T00:00:00"}
        with patch.object(km, "fetch_pypi", return_value=meta) as mock_fetch:
            km.get_or_fetch("fastapi", "pypi")
        mock_fetch.assert_called_once()

    def test_saves_cache_after_fetch(self, km, cache_path):
        meta = {"name": "requests", "exists": True, "fetched_at": "2099-01-01T00:00:00"}
        with patch.object(km, "fetch_pypi", return_value=meta):
            km.get_or_fetch("requests", "pypi")
        assert cache_path.exists()
        data = json.loads(cache_path.read_text())
        assert "pypi:requests" in data

    def test_returns_none_on_fetch_failure(self, km):
        with patch.object(km, "fetch_pypi", return_value=None):
            result = km.get_or_fetch("totally-fake-xyz-abc", "pypi")
        assert result is None

    def test_unknown_ecosystem_returns_none(self, km):
        result = km.get_or_fetch("something", "conda")
        assert result is None


# ── verify_and_enrich ────────────────────────────────────────────


class TestVerifyAndEnrich:

    def test_static_alias_resolved_offline(self, km):
        """sklearn → scikit-learn must work with no network calls."""
        spec = {"packages": [{"name": "sklearn", "version": None, "extras": []}]}
        with patch.object(km, "get_or_fetch") as mock_fetch:
            updated, changes = km.verify_and_enrich(spec, "pypi")
        # Should not hit the network for a known static alias
        mock_fetch.assert_not_called()
        assert updated["packages"][0]["name"] == "scikit-learn"
        assert any("sklearn" in c for c in changes)

    def test_already_canonical_name_unchanged(self, km):
        """scikit-learn is already correct — no network needed if cache hit."""
        from datetime import datetime
        km._cache["pypi:scikit-learn"] = {
            "name": "scikit-learn",
            "exists": True,
            "fetched_at": datetime.now().isoformat(),
        }
        spec = {"packages": [{"name": "scikit-learn", "version": None, "extras": []}]}
        updated, changes = km.verify_and_enrich(spec, "pypi")
        assert updated["packages"][0]["name"] == "scikit-learn"
        assert changes == []

    def test_registry_corrects_casing(self, km):
        """PyPI returns 'Pillow'; we passed 'pillow' — should be corrected."""
        meta = {
            "name": "Pillow",
            "exists": True,
            "fetched_at": "2099-01-01T00:00:00",
        }
        with patch.object(km, "get_or_fetch", return_value=meta):
            spec = {"packages": [{"name": "pillow", "version": None, "extras": []}]}
            updated, changes = km.verify_and_enrich(spec, "pypi")
        assert updated["packages"][0]["name"] == "Pillow"
        assert any("pillow" in c.lower() for c in changes)

    def test_unknown_package_left_unchanged(self, km):
        """Packages not resolvable are passed through as-is."""
        with patch.object(km, "get_or_fetch", return_value=None):
            spec = {"packages": [{"name": "my-obscure-internal-lib"}]}
            updated, changes = km.verify_and_enrich(spec, "pypi")
        assert updated["packages"][0]["name"] == "my-obscure-internal-lib"
        assert changes == []

    def test_multiple_packages_mixed(self, km):
        """Mix of alias, correct, and unknown packages in one spec."""
        from datetime import datetime
        km._cache["pypi:requests"] = {
            "name": "requests",
            "exists": True,
            "fetched_at": datetime.now().isoformat(),
        }
        with patch.object(km, "get_or_fetch") as mock_fetch:
            # requests is cached; unknown-lib triggers a fetch that returns None
            def side_effect(name, eco):
                if name == "requests":
                    return km._cache["pypi:requests"]
                return None
            mock_fetch.side_effect = side_effect

            spec = {
                "packages": [
                    {"name": "sklearn"},      # static alias → scikit-learn
                    {"name": "requests"},     # cached, no change
                    {"name": "unknown-lib"},  # not found, unchanged
                ]
            }
            updated, changes = km.verify_and_enrich(spec, "pypi")

        names = [p["name"] for p in updated["packages"]]
        assert names[0] == "scikit-learn"
        assert names[1] == "requests"
        assert names[2] == "unknown-lib"
        assert len(changes) == 1  # only sklearn was corrected

    def test_empty_packages_list(self, km):
        spec = {"packages": []}
        updated, changes = km.verify_and_enrich(spec, "pypi")
        assert updated["packages"] == []
        assert changes == []

    def test_original_spec_dict_not_mutated(self, km):
        """verify_and_enrich must not mutate the input dict in place."""
        spec = {"packages": [{"name": "sklearn"}]}
        original_name = spec["packages"][0]["name"]
        km.verify_and_enrich(spec, "pypi")
        assert spec["packages"][0]["name"] == original_name


# ── refresh_stale ────────────────────────────────────────────────


class TestRefreshStale:

    def test_refreshes_only_stale_entries(self, km, cache_path):
        from datetime import datetime, timedelta
        now = datetime.now()
        km._cache = {
            "pypi:fresh": {"name": "fresh", "exists": True, "fetched_at": now.isoformat()},
            "pypi:stale": {
                "name": "stale",
                "exists": True,
                "fetched_at": (now - timedelta(days=30)).isoformat(),
            },
        }
        fresh_meta = {"name": "stale", "exists": True, "fetched_at": now.isoformat()}
        with patch.object(km, "fetch_pypi", return_value=fresh_meta) as mock_fetch:
            count = km.refresh_stale("pypi")
        assert count == 1
        mock_fetch.assert_called_once_with("stale")

    def test_ecosystem_filter(self, km):
        from datetime import datetime, timedelta
        old_ts = (datetime.now() - timedelta(days=30)).isoformat()
        km._cache = {
            "pypi:stale-py": {"name": "stale-py", "exists": True, "fetched_at": old_ts},
            "npm:stale-js": {"name": "stale-js", "exists": True, "fetched_at": old_ts},
        }
        with patch.object(km, "fetch_pypi", return_value=None):
            count = km.refresh_stale("pypi")
        assert count == 0  # fetch returned None, so count stays 0

    def test_returns_zero_when_nothing_stale(self, km):
        from datetime import datetime
        km._cache["pypi:fresh"] = {
            "name": "fresh",
            "exists": True,
            "fetched_at": datetime.now().isoformat(),
        }
        count = km.refresh_stale("pypi")
        assert count == 0


# ── cache_stats ───────────────────────────────────────────────────


class TestCacheStats:

    def test_empty_cache(self, km):
        stats = km.cache_stats()
        assert stats["total"] == 0
        assert stats["stale"] == 0
        assert stats["by_ecosystem"] == {}

    def test_counts_by_ecosystem(self, km):
        from datetime import datetime
        now = datetime.now().isoformat()
        km._cache = {
            "pypi:a": {"exists": True, "fetched_at": now},
            "pypi:b": {"exists": True, "fetched_at": now},
            "npm:c": {"exists": True, "fetched_at": now},
        }
        stats = km.cache_stats()
        assert stats["total"] == 3
        assert stats["by_ecosystem"]["pypi"] == 2
        assert stats["by_ecosystem"]["npm"] == 1


# ── get_knowledge_manager ─────────────────────────────────────────


class TestGetKnowledgeManager:

    def test_returns_instance(self, monkeypatch, tmp_path):
        from shellock_core.core import knowledge, registry
        monkeypatch.setattr(registry, "SHELLOCK_HOME", tmp_path)
        (tmp_path / "knowledge").mkdir()
        mgr = knowledge.get_knowledge_manager()
        assert isinstance(mgr, PackageKnowledgeManager)
        assert mgr.cache_path == tmp_path / "knowledge" / "packages.json"
