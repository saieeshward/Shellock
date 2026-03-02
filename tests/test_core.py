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
