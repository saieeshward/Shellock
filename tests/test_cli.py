"""Tests for Shellock CLI helpers and new commands."""

import os
import tempfile
import shutil
from pathlib import Path

import pytest

from shellock_core.cli import _sanitize_env_id


# ── _sanitize_env_id ────────────────────────────────────────────


class TestSanitizeEnvId:

    def test_basic_name(self):
        assert _sanitize_env_id("my-project") == "my-project"

    def test_spaces_become_hyphens(self):
        assert _sanitize_env_id("my cool project") == "my-cool-project"

    def test_special_chars_replaced(self):
        assert _sanitize_env_id("my@project!v2") == "my-project-v2"

    def test_uppercase_lowered(self):
        assert _sanitize_env_id("MyProject") == "myproject"

    def test_multiple_hyphens_collapsed(self):
        assert _sanitize_env_id("my---project") == "my-project"

    def test_leading_trailing_hyphens_stripped(self):
        assert _sanitize_env_id("--project--") == "project"

    def test_empty_string_fallback(self):
        assert _sanitize_env_id("") == "shellock-env"

    def test_only_special_chars_fallback(self):
        assert _sanitize_env_id("@#$%") == "shellock-env"

    def test_dots_and_underscores_preserved(self):
        assert _sanitize_env_id("my.project_v2") == "my.project_v2"

    def test_unicode_replaced(self):
        result = _sanitize_env_id("café-résumé")
        assert result == "caf-r-sum"  # non-ascii replaced with hyphens

    def test_whitespace_stripped(self):
        assert _sanitize_env_id("  my-env  ") == "my-env"


# ── ActionEntry with failed_stderr ──────────────────────────────


class TestActionEntryFailedStderr:

    def test_action_entry_stores_failed_stderr(self):
        from shellock_core.core.schemas import ActionEntry, ActionType

        entry = ActionEntry(
            id="act-test01",
            type=ActionType.INIT,
            result="failed",
            failed_stderr="ModuleNotFoundError: No module named 'numpy'",
        )
        assert entry.failed_stderr == "ModuleNotFoundError: No module named 'numpy'"

    def test_action_entry_none_stderr_by_default(self):
        from shellock_core.core.schemas import ActionEntry, ActionType

        entry = ActionEntry(id="act-test02", type=ActionType.INIT, result="success")
        assert entry.failed_stderr is None


# ── Environment helpers ─────────────────────────────────────────


class TestEnvHelpers:

    def test_get_env_info_reads_pyvenv_cfg(self):
        """Verify _get_env_info reads Python version from pyvenv.cfg."""
        from shellock_core.core.ui import _get_env_info

        with tempfile.TemporaryDirectory() as tmpdir:
            env_dir = Path(tmpdir)
            cfg = env_dir / "pyvenv.cfg"
            cfg.write_text("home = /usr/bin\nversion = 3.11.4\n")

            info = _get_env_info(env_dir)
            assert info["python_version"] == "3.11.4"

    def test_get_env_info_no_cfg(self):
        """Verify _get_env_info handles missing pyvenv.cfg."""
        from shellock_core.core.ui import _get_env_info

        with tempfile.TemporaryDirectory() as tmpdir:
            info = _get_env_info(Path(tmpdir))
            assert "python_version" not in info

    def test_show_activation_hint_not_crash(self):
        """Verify show_activation_hint runs without errors."""
        # This function was removed during refactor, but if it exists, test it
        try:
            from shellock_core.core.ui import show_activation_hint
            # should not crash
            show_activation_hint("/tmp/fake-env")
        except ImportError:
            # function was removed in favour of prompt_activate, that's fine
            pass


# ── Unified approval screen helpers ─────────────────────────────


class TestUIHelpers:

    def test_show_plan_preview_no_crash(self, monkeypatch):
        """show_plan_preview should render without errors."""
        from shellock_core.core.ui import show_plan_preview
        from shellock_core.core.schemas import Command, EnvSpec, Impact

        spec = EnvSpec(env_id="test-env", module="python")
        commands = [
            Command(command="pip install flask", impact=Impact.SAFE, description="install flask"),
        ]
        # _plain_approval calls input(), so we mock it
        monkeypatch.setattr("builtins.input", lambda _: "yes")
        os.environ["SHELLOCK_PLAIN"] = "1"
        try:
            show_plan_preview(spec, commands, warnings=None)
        finally:
            os.environ.pop("SHELLOCK_PLAIN", None)

    def test_show_explain_no_crash(self):
        """show_explain should render without errors."""
        from shellock_core.core.ui import show_explain
        from shellock_core.core.schemas import EnvSpec

        spec = EnvSpec(env_id="test-env", module="python", reasoning="Test reasoning")
        os.environ["SHELLOCK_PLAIN"] = "1"
        try:
            show_explain(spec)
        finally:
            os.environ.pop("SHELLOCK_PLAIN", None)

    def test_show_env_details_no_crash(self):
        """show_env_details renders without errors for a temp dir."""
        from shellock_core.core.ui import show_env_details

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Path(tmpdir) / "pyvenv.cfg"
            cfg.write_text("version = 3.12.0\n")
            os.environ["SHELLOCK_PLAIN"] = "1"
            try:
                show_env_details(Path(tmpdir))
            finally:
                os.environ.pop("SHELLOCK_PLAIN", None)

    def test_show_envs_no_crash(self):
        """show_envs renders without errors."""
        from shellock_core.core.ui import show_envs

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake environment dir
            env = Path(tmpdir) / "fake-env"
            env.mkdir()
            (env / "pyvenv.cfg").write_text("version = 3.11.0\n")

            os.environ["SHELLOCK_PLAIN"] = "1"
            try:
                show_envs(Path(tmpdir))
            finally:
                os.environ.pop("SHELLOCK_PLAIN", None)
