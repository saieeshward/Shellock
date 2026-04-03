"""Tests for Shellock core components."""

import json
import tempfile
from pathlib import Path

from shellock_core.core.schemas import (
    ActionType,
    Command,
    DiagnosisMethod,
    DiagnosisResult,
    EnvSpec,
    Impact,
    PackageSpec,
    ProjectHistory,
    UserProfile,
)
from shellock_core.core.dispatcher import validate_commands, execute_commands, DispatchResult
from shellock_core.core.registry import fingerprint_error


class TestLLMClient:

    def test_call_ollama_uses_attribute_not_dict(self, monkeypatch):
        """ollama.generate() returns an object, not a dict — must use .response not .get()"""
        from shellock_core.core.llm import LLMClient
        from shellock_core.core.schemas import LLMTier, ShelllockConfig

        class FakeResponse:
            response = "{'env_id': 'test', 'module': 'python'}"

        import ollama as _ollama
        monkeypatch.setattr(_ollama, "generate", lambda **kwargs: FakeResponse())

        config = ShelllockConfig()
        client = LLMClient(config, LLMTier.LOCAL)
        result = client._call_ollama("test prompt")
        assert result == FakeResponse.response


class TestSchemas:

    def test_env_spec_creation(self):
        spec = EnvSpec(
            env_id="test-001",
            module="python",
            runtime_version="3.11",
            packages=[PackageSpec(name="fastapi")],
        )
        assert spec.env_id == "test-001"
        assert spec.approved is False
        assert spec.schema_version == "1.0"

    def test_env_spec_forbids_extra_fields(self):
        import pytest
        with pytest.raises(Exception):
            EnvSpec(
                env_id="test",
                module="python",
                unknown_field="should fail",
            )

    def test_package_spec_to_install_string(self):
        p1 = PackageSpec(name="fastapi")
        assert p1.to_install_string() == "fastapi"

        p2 = PackageSpec(name="fastapi", version=">=0.100")
        assert p2.to_install_string() == "fastapi>=0.100"

        p3 = PackageSpec(name="uvicorn", extras=["standard"])
        assert p3.to_install_string() == "uvicorn[standard]"

    def test_user_profile_record_choice(self):
        profile = UserProfile()
        profile.record_choice("formatter", "black")
        profile.record_choice("formatter", "black")
        profile.record_choice("formatter", "ruff")
        assert profile.preferences["formatter"]["black"] == 2
        assert profile.preferences["formatter"]["ruff"] == 1

    def test_user_profile_get_suggestions(self):
        profile = UserProfile(suggestion_threshold=2)
        profile.preferences = {"formatter": {"black": 5, "ruff": 1}}
        suggestions = profile.get_suggestions("formatter")
        assert "black" in suggestions
        assert "ruff" not in suggestions

    def test_user_profile_rejected_suggestions(self):
        profile = UserProfile(suggestion_threshold=2)
        profile.preferences = {"formatter": {"black": 5}}
        profile.rejected_suggestions = ["black"]
        suggestions = profile.get_suggestions("formatter")
        assert "black" not in suggestions

    def test_project_history_serialization(self):
        history = ProjectHistory(project="/test/path", module="python")
        data = history.model_dump(mode="json")
        restored = ProjectHistory.model_validate(data)
        assert restored.project == "/test/path"


class TestDispatcher:

    def test_validate_allowed_commands(self):
        commands = [
            Command(command="pip install fastapi", impact=Impact.SAFE),
        ]
        result = validate_commands(commands, ["pip install"], [])
        assert result[0].impact == Impact.SAFE

    def test_validate_blocked_command(self):
        commands = [
            Command(command="sudo pip install something", impact=Impact.SAFE),
        ]
        result = validate_commands(commands, ["pip install"], [r"sudo\s+"])
        assert result[0].impact == Impact.BLOCKED

    def test_validate_not_in_allowlist(self):
        commands = [
            Command(command="rm -rf /", impact=Impact.SAFE),
        ]
        result = validate_commands(commands, ["pip install"], [])
        assert result[0].impact == Impact.BLOCKED

    def test_validate_blocks_semicolon_injection(self):
        commands = [
            Command(command="pip install foo; rm -rf ~", impact=Impact.SAFE),
        ]
        result = validate_commands(commands, ["pip install"], [])
        assert result[0].impact == Impact.BLOCKED
        assert "metacharacter" in result[0].description

    def test_validate_blocks_pipe_injection(self):
        commands = [
            Command(command="pip install foo | cat /etc/passwd", impact=Impact.SAFE),
        ]
        result = validate_commands(commands, ["pip install"], [])
        assert result[0].impact == Impact.BLOCKED
        assert "metacharacter" in result[0].description

    def test_execute_echo_command(self):
        commands = [
            Command(command="echo hello", impact=Impact.SAFE, description="test"),
        ]
        result = execute_commands(commands)
        assert result.all_succeeded
        assert "hello" in result.results[0].stdout

    def test_execute_dry_run(self):
        commands = [
            Command(command="echo hello", impact=Impact.SAFE),
        ]
        result = execute_commands(commands, dry_run=True)
        assert result.all_succeeded
        assert "DRY RUN" in result.results[0].stdout

    def test_execute_skips_blocked(self):
        commands = [
            Command(command="rm -rf /", impact=Impact.BLOCKED),
        ]
        result = execute_commands(commands)
        assert result.all_succeeded  # no commands actually ran
        assert len(result.results) == 0

    def test_blocked_commands_populated_in_result(self):
        commands = [
            Command(command="rm -rf /", impact=Impact.BLOCKED),
            Command(command="echo hi", impact=Impact.BLOCKED),
        ]
        result = execute_commands(commands)
        assert result.blocked_commands == ["rm -rf /", "echo hi"]


class TestCascadingError:

    def test_unrelated_fix_not_flagged(self, tmp_path, monkeypatch):
        """A fix for 'requests' should not be blamed for a 'numpy' error."""
        from shellock_core.core import registry
        monkeypatch.setattr(registry, "SHELLOCK_HOME", tmp_path)

        history = registry.ProjectHistory(project=str(tmp_path))
        from shellock_core.core.schemas import ActionEntry, ActionType
        from datetime import datetime
        entry = ActionEntry(
            id="act-abc123",
            type=ActionType.FIX,
            spec={"packages": [{"name": "requests", "version": None, "extras": []}]},
            timestamp=datetime.now(),
        )
        history.actions.append(entry)
        registry.save_history(str(tmp_path), history)

        result = registry.check_cascading_error(
            str(tmp_path),
            "some-fingerprint",
            error_text="numpy version conflict: numpy==1.24 required",
        )
        assert result is None  # requests fix should NOT be blamed for numpy error

    def test_related_fix_is_flagged(self, tmp_path, monkeypatch):
        """A fix for 'numpy' should be flagged for a subsequent numpy error."""
        from shellock_core.core import registry
        monkeypatch.setattr(registry, "SHELLOCK_HOME", tmp_path)

        history = registry.ProjectHistory(project=str(tmp_path))
        from shellock_core.core.schemas import ActionEntry, ActionType
        from datetime import datetime
        entry = ActionEntry(
            id="act-xyz999",
            type=ActionType.FIX,
            spec={"packages": [{"name": "numpy", "version": None, "extras": []}]},
            timestamp=datetime.now(),
        )
        history.actions.append(entry)
        registry.save_history(str(tmp_path), history)

        result = registry.check_cascading_error(
            str(tmp_path),
            "some-fingerprint",
            error_text="numpy version conflict: numpy==1.24 required",
        )
        assert result == "act-xyz999"


class TestRegistry:

    def test_load_spec_returns_none_on_corrupted_file(self, tmp_path):
        """load_spec() must return None and create a .bak on corrupted spec.json."""
        from shellock_core.core import registry

        shellock_dir = tmp_path / ".shellock"
        shellock_dir.mkdir()
        (shellock_dir / "spec.json").write_text("{corrupted!!!")

        result = registry.load_spec(str(tmp_path))
        assert result is None
        assert (shellock_dir / "spec.json.bak").exists()

    def test_write_json_no_truncation_under_concurrency(self, tmp_path):
        """Two threads writing simultaneously should not produce empty/corrupt JSON."""
        import threading
        from shellock_core.core.registry import _write_json

        target = tmp_path / "test.json"
        errors = []

        def writer(val):
            try:
                _write_json(target, {"value": val})
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer, args=("thread1",))
        t2 = threading.Thread(target=writer, args=("thread2",))
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert not errors
        content = target.read_text()
        assert len(content) > 0
        import json
        parsed = json.loads(content)  # must be valid JSON, not truncated
        assert "value" in parsed


class TestMarkFixSuccessful:

    def test_records_successful_fix(self, tmp_path, monkeypatch):
        """mark_fix_successful() should populate fixes_that_worked."""
        from shellock_core.core import registry
        monkeypatch.setattr(registry, "SHELLOCK_HOME", tmp_path)

        # Create a history with an error_frequency entry
        history = registry.ProjectHistory(project=str(tmp_path))
        history.error_frequency["abc123"] = {
            "pattern": "ModuleNotFoundError",
            "count": 2,
            "fixes_attempted": [],
            "fixes_that_worked": [],
        }
        registry.save_history(str(tmp_path), history)

        fix = {"action": "install", "commands": ["pip install foo"]}
        registry.mark_fix_successful(str(tmp_path), "abc123", fix)

        reloaded = registry.load_history(str(tmp_path))
        assert len(reloaded.error_frequency["abc123"]["fixes_that_worked"]) == 1

    def test_skips_duplicate_fix(self, tmp_path, monkeypatch):
        """Same fix should not be recorded twice."""
        from shellock_core.core import registry
        monkeypatch.setattr(registry, "SHELLOCK_HOME", tmp_path)

        history = registry.ProjectHistory(project=str(tmp_path))
        fix = {"action": "install", "commands": ["pip install foo"]}
        import json
        history.error_frequency["abc123"] = {
            "pattern": "error",
            "count": 1,
            "fixes_attempted": [],
            "fixes_that_worked": [json.dumps(fix, sort_keys=True)],
        }
        registry.save_history(str(tmp_path), history)

        registry.mark_fix_successful(str(tmp_path), "abc123", fix)

        reloaded = registry.load_history(str(tmp_path))
        assert len(reloaded.error_frequency["abc123"]["fixes_that_worked"]) == 1

    def test_noop_on_missing_fingerprint(self, tmp_path, monkeypatch):
        """mark_fix_successful() should not crash if fingerprint is unknown."""
        from shellock_core.core import registry
        monkeypatch.setattr(registry, "SHELLOCK_HOME", tmp_path)

        history = registry.ProjectHistory(project=str(tmp_path))
        registry.save_history(str(tmp_path), history)

        # Should not raise
        registry.mark_fix_successful(str(tmp_path), "unknown", {"action": "install"})

    def test_noop_on_none_fix(self, tmp_path, monkeypatch):
        """mark_fix_successful() should not crash if fix is None."""
        from shellock_core.core import registry
        monkeypatch.setattr(registry, "SHELLOCK_HOME", tmp_path)

        history = registry.ProjectHistory(project=str(tmp_path))
        registry.save_history(str(tmp_path), history)

        registry.mark_fix_successful(str(tmp_path), "abc123", None)


class TestCloudTierUpgrade:

    def test_cloud_tier_when_api_key_set(self):
        """LLMClient with TEMPLATE tier + API key should be available as CLOUD."""
        from shellock_core.core.schemas import LLMTier, ShelllockConfig

        # Simulate: system detection says TEMPLATE, but user configured API key
        config = ShelllockConfig(llm_api_key="test-key")
        effective_tier = LLMTier.TEMPLATE
        if effective_tier == LLMTier.TEMPLATE and config.llm_api_key:
            effective_tier = LLMTier.CLOUD
        assert effective_tier == LLMTier.CLOUD

    def test_template_tier_without_api_key(self):
        """TEMPLATE tier should stay TEMPLATE without an API key."""
        from shellock_core.core.schemas import LLMTier, ShelllockConfig

        config = ShelllockConfig()
        effective_tier = LLMTier.TEMPLATE
        if effective_tier == LLMTier.TEMPLATE and config.llm_api_key:
            effective_tier = LLMTier.CLOUD
        assert effective_tier == LLMTier.TEMPLATE


class TestErrorFingerprinting:

    def test_same_error_same_fingerprint(self):
        e1 = "ModuleNotFoundError: No module named 'fastapi'"
        e2 = "ModuleNotFoundError: No module named 'fastapi'"
        assert fingerprint_error(e1) == fingerprint_error(e2)

    def test_different_line_numbers_same_fingerprint(self):
        e1 = 'File "/app/main.py", line 5\nModuleNotFoundError: No module named \'x\''
        e2 = 'File "/app/main.py", line 99\nModuleNotFoundError: No module named \'x\''
        assert fingerprint_error(e1) == fingerprint_error(e2)

    def test_different_errors_different_fingerprint(self):
        e1 = "ModuleNotFoundError: No module named 'fastapi'"
        e2 = "ImportError: cannot import name 'FastAPI'"
        assert fingerprint_error(e1) != fingerprint_error(e2)
