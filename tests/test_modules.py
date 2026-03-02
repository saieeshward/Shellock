"""Tests for Shellock modules — proves the modular interface works."""

import tempfile
from pathlib import Path

from shellock_core.modules.python.module import PythonModule
from shellock_core.modules.node.module import NodeModule


class TestPythonModule:

    def setup_method(self):
        self.module = PythonModule()

    def test_detect_requirements_txt(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n")
        assert self.module.detect(str(tmp_path)) is True

    def test_detect_pyproject_toml(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        assert self.module.detect(str(tmp_path)) is True

    def test_detect_empty_dir(self, tmp_path):
        assert self.module.detect(str(tmp_path)) is False

    def test_build_spec_from_description(self):
        context = {"introspection": {}}
        spec = self.module.build_spec("python 3.11 fastapi project with black", context)
        assert spec["module"] == "python"
        assert spec["runtime_version"] == "3.11"
        packages = [p["name"] for p in spec["packages"]]
        assert "fastapi" in packages
        assert "black" in packages

    def test_dispatch_creates_venv_commands(self):
        spec = {
            "env_id": "test-env",
            "module": "python",
            "runtime_version": "3.11",
            "packages": [{"name": "fastapi"}, {"name": "black"}],
            "env_path": "/tmp/test-shellock-env",
            "post_hooks": [],
        }
        commands = self.module.dispatch(spec)
        assert len(commands) >= 2  # venv creation + pip install
        assert "venv" in commands[0]["command"]
        assert "pip install" in commands[-1]["command"]

    def test_diagnose_module_not_found(self):
        stderr = "ModuleNotFoundError: No module named 'nonexistent_xyz_package'"
        result = self.module.diagnose(stderr, {})
        assert result is not None
        assert "pip install" in result["commands"][0]

    def test_diagnose_externally_managed(self):
        stderr = "error: externally-managed-environment"
        result = self.module.diagnose(stderr, {})
        assert result is not None
        assert "venv" in result["commands"][0]

    def test_introspect_returns_python_info(self):
        info = self.module.introspect(".")
        assert "python_version" in info
        assert "installed_packages" in info
        assert isinstance(info["installed_packages"], dict)

    def test_validate_spec_returns_list(self):
        spec = {"packages": [{"name": "fastapi"}]}
        warnings = self.module.validate_spec(spec)
        assert isinstance(warnings, list)

    def test_onboarding_questions(self):
        questions = self.module.onboarding_questions()
        assert len(questions) >= 1
        assert all("key" in q and "question" in q for q in questions)

    def test_error_patterns_load(self):
        patterns = self.module.load_error_patterns()
        assert len(patterns) > 0
        assert all("match" in p for p in patterns)


class TestNodeModule:

    def setup_method(self):
        self.module = NodeModule()

    def test_detect_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        assert self.module.detect(str(tmp_path)) is True

    def test_detect_empty_dir(self, tmp_path):
        assert self.module.detect(str(tmp_path)) is False

    def test_build_spec_from_description(self):
        context = {"introspection": {}}
        spec = self.module.build_spec("node react app with typescript", context)
        assert spec["module"] == "node"
        packages = [p["name"] for p in spec["packages"]]
        assert "react" in packages
        assert "typescript" in packages

    def test_dispatch_creates_npm_commands(self):
        spec = {
            "env_id": "test-node",
            "module": "node",
            "packages": [{"name": "express"}],
        }
        commands = self.module.dispatch(spec)
        assert len(commands) >= 1
        assert any("npm install" in c["command"] for c in commands)

    def test_diagnose_eresolve(self):
        stderr = "npm ERR! ERESOLVE unable to resolve dependency tree"
        result = self.module.diagnose(stderr, {})
        assert result is not None
        assert "--legacy-peer-deps" in result["commands"][0]

    def test_diagnose_module_not_found(self):
        stderr = "Error: Cannot find module 'express'"
        result = self.module.diagnose(stderr, {})
        assert result is not None
        assert "npm install express" in result["commands"][0]

    def test_onboarding_questions(self):
        questions = self.module.onboarding_questions()
        assert len(questions) >= 1

    def test_error_patterns_load(self):
        patterns = self.module.load_error_patterns()
        assert len(patterns) > 0


class TestModuleInterface:
    """Prove that both modules implement the same interface."""

    def test_both_modules_have_required_attributes(self):
        for ModClass in [PythonModule, NodeModule]:
            mod = ModClass()
            assert hasattr(mod, "name")
            assert hasattr(mod, "description")
            assert hasattr(mod, "triggers")
            assert hasattr(mod, "allowed_commands")
            assert hasattr(mod, "blocked_patterns")
            assert hasattr(mod, "suggestable_tools")

    def test_both_modules_have_required_methods(self):
        for ModClass in [PythonModule, NodeModule]:
            mod = ModClass()
            assert callable(getattr(mod, "detect"))
            assert callable(getattr(mod, "onboarding_questions"))
            assert callable(getattr(mod, "introspect"))
            assert callable(getattr(mod, "build_spec"))
            assert callable(getattr(mod, "validate_spec"))
            assert callable(getattr(mod, "dispatch"))
            assert callable(getattr(mod, "diagnose"))
            assert callable(getattr(mod, "handle_error"))
