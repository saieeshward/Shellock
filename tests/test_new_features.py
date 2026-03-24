"""Tests for new Shellock features added during build phase."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from shellock_core.cli import _sanitize_env_id, _infer_module_from_description


# ── Module inference from description ──────────────────────────


class TestModuleInference:

    def test_npm_description_selects_node(self):
        mod = _infer_module_from_description("npm Next.js + Tailwind")
        assert mod.name == "node"

    def test_react_description_selects_node(self):
        mod = _infer_module_from_description("react app with typescript")
        assert mod.name == "node"

    def test_python_description_selects_python(self):
        mod = _infer_module_from_description("python fastapi project")
        assert mod.name == "python"

    def test_ambiguous_defaults_to_python(self):
        mod = _infer_module_from_description("web server project")
        assert mod.name == "python"

    def test_node_keyword_selects_node(self):
        mod = _infer_module_from_description("node express server")
        assert mod.name == "node"

    def test_vue_selects_node(self):
        mod = _infer_module_from_description("vue frontend app")
        assert mod.name == "node"


# ── Package name alias parsing ─────────────────────────────────


class TestPackageAliases:

    def test_node_next_js_alias(self):
        from shellock_core.modules.node.module import NodeModule
        mod = NodeModule()
        pkgs = mod._parse_packages_from_description("Next.js + Tailwind app")
        assert "next" in pkgs
        assert "tailwindcss" in pkgs

    def test_node_nextjs_alias(self):
        from shellock_core.modules.node.module import NodeModule
        mod = NodeModule()
        pkgs = mod._parse_packages_from_description("nextjs react project")
        assert "next" in pkgs
        assert "react" in pkgs

    def test_python_postgres_alias(self):
        from shellock_core.modules.python.module import PythonModule
        mod = PythonModule()
        pkgs = mod._parse_packages_from_description("fastapi + postgres")
        assert "fastapi" in pkgs
        assert "psycopg2-binary" in pkgs

    def test_python_sklearn_alias(self):
        from shellock_core.modules.python.module import PythonModule
        mod = PythonModule()
        pkgs = mod._parse_packages_from_description("sklearn pandas numpy")
        assert "scikit-learn" in pkgs
        assert "pandas" in pkgs
        assert "numpy" in pkgs


# ── Corrupted data file handling ───────────────────────────────


class TestCorruptedDataHandling:

    def test_corrupted_profile_recovers(self, tmp_path, monkeypatch):
        from shellock_core.core import registry
        monkeypatch.setattr(registry, "SHELLOCK_HOME", tmp_path)
        monkeypatch.setattr(registry, "PROFILE_PATH", tmp_path / "profile.json")

        # Write corrupted JSON
        (tmp_path / "profile.json").write_text("{corrupted data!!!")
        profile = registry.load_profile()
        assert profile.onboarding_complete is False  # got a fresh default

        # Backup should exist
        assert (tmp_path / "profile.json.bak").exists()

    def test_corrupted_config_recovers(self, tmp_path, monkeypatch):
        from shellock_core.core import registry
        monkeypatch.setattr(registry, "SHELLOCK_HOME", tmp_path)
        monkeypatch.setattr(registry, "CONFIG_PATH", tmp_path / "config.json")

        (tmp_path / "config.json").write_text("not json at all")
        config = registry.load_config()
        assert config.llm_provider == "ollama"  # default

    def test_corrupted_history_recovers(self, tmp_path):
        from shellock_core.core import registry

        shellock_dir = tmp_path / ".shellock"
        shellock_dir.mkdir()
        (shellock_dir / "history.json").write_text("{{bad json}}")
        history = registry.load_history(str(tmp_path))
        assert len(history.actions) == 0  # fresh default


# ── Adaptive announcements ─────────────────────────────────────


class TestAdaptive:

    def test_suggest_from_preferences(self):
        from shellock_core.core.adaptive import suggest_from_preferences
        from shellock_core.core.schemas import UserProfile

        profile = UserProfile(suggestion_threshold=2)
        profile.preferences = {"tools": {"black": 5, "ruff": 1}}

        os.environ["SHELLOCK_PLAIN"] = "1"
        try:
            suggestions = suggest_from_preferences(profile, "tools", [])
            assert "black" in suggestions
            assert "ruff" not in suggestions
        finally:
            os.environ.pop("SHELLOCK_PLAIN", None)

    def test_suggest_excludes_current(self):
        from shellock_core.core.adaptive import suggest_from_preferences
        from shellock_core.core.schemas import UserProfile

        profile = UserProfile(suggestion_threshold=2)
        profile.preferences = {"tools": {"black": 5}}

        os.environ["SHELLOCK_PLAIN"] = "1"
        try:
            suggestions = suggest_from_preferences(profile, "tools", ["black"])
            assert "black" not in suggestions
        finally:
            os.environ.pop("SHELLOCK_PLAIN", None)


# ── LLM Client ────────────────────────────────────────────────


class TestLLMClient:

    def test_extract_json_from_markdown(self):
        from shellock_core.core.llm import LLMClient
        text = '```json\n{"env_id": "test", "module": "python"}\n```'
        result = LLMClient._extract_json(text)
        assert result is not None
        assert result["env_id"] == "test"

    def test_extract_json_plain(self):
        from shellock_core.core.llm import LLMClient
        text = '{"env_id": "test"}'
        result = LLMClient._extract_json(text)
        assert result == {"env_id": "test"}

    def test_extract_json_invalid(self):
        from shellock_core.core.llm import LLMClient
        result = LLMClient._extract_json("not json at all")
        assert result is None

    def test_cloud_model_default(self):
        from shellock_core.core.llm import LLMClient
        assert "gemini" in LLMClient.CLOUD_MODEL


# ── Registry: snapshots and lock files ─────────────────────────


class TestRegistryFeatures:

    def test_snapshot_nonexistent_env(self):
        from shellock_core.core.registry import save_snapshot
        result = save_snapshot("/nonexistent/path/no-env")
        assert result is None

    def test_lock_file_nonexistent_env(self):
        from shellock_core.core.registry import write_lock_file
        result = write_lock_file("/nonexistent/path/no-env", "python")
        assert result is None

    def test_security_scan_nonexistent(self):
        from shellock_core.core.registry import run_security_scan
        result = run_security_scan("/nonexistent/path", "python")
        assert result["scanned"] is False


# ── Plain mode plan display (--yes fix) ────────────────────────


class TestPlainPlanDisplay:

    def test_plain_plan_display_no_prompt(self, capsys):
        from shellock_core.core.ui import _plain_plan_display
        from shellock_core.core.schemas import Command, EnvSpec, Impact

        spec = EnvSpec(env_id="test-env", module="python")
        commands = [Command(command="pip install flask", impact=Impact.SAFE)]

        _plain_plan_display(spec, commands)
        captured = capsys.readouterr()
        assert "auto-approved" in captured.out
        assert "pip install flask" in captured.out


# ── Node module missing function ───────────────────────────────


class TestNodeInstallHint:

    def test_node_install_hint_returns_string(self):
        from shellock_core.modules.node.module import _node_install_hint
        hint = _node_install_hint()
        assert isinstance(hint, str)
        assert len(hint) > 0
