"""Python ecosystem module.

Handles Python virtual environments, package installation,
version management, and Python-specific error diagnosis.

Uses Python's own introspection (importlib.metadata, sys, sysconfig)
as the first line of defence — faster and more accurate than any LLM.
"""

from __future__ import annotations

import difflib
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any

from shellock_core.module_base import ShellockModule


class PythonModule(ShellockModule):

    name = "python"
    description = "Python virtual environments, packages, and version management"

    triggers = [
        "requirements.txt",
        "pyproject.toml",
        "Pipfile",
        "setup.py",
        "setup.cfg",
        "tox.ini",
        ".python-version",
    ]

    allowed_commands = [
        "pip install",
        "pip uninstall",
        "pip list",
        "pip show",
        "pip freeze",
        "python -m venv",
        "python3 -m venv",
        "python3.",           # matches python3.11, python3.12, etc.
        "pyenv install",
        "pyenv local",
        "pyenv global",
        "source",             # for venv activation hints
    ]

    blocked_patterns = [
        r"sudo\s+",
        r"rm\s+-rf",
        r"rm\s+-r\s+/",
        r"chmod\s+777",
        r">\s*/etc/",
        r"\|\s*sh$",
        r"\|\s*bash$",
        r"pip\s+install\s+--break-system-packages",
    ]

    suggestable_tools = [
        "black", "ruff", "pytest", "mypy", "isort",
        "flake8", "pylint", "pre-commit", "ipython",
    ]

    # ── Detection ───────────────────────────────────────────────

    def detect(self, project_path: str) -> bool:
        path = Path(project_path)
        return any((path / trigger).exists() for trigger in self.triggers)

    # ── Onboarding ──────────────────────────────────────────────

    def onboarding_questions(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "python_env",
                "question": "Preferred Python env tool?",
                "options": ["venv", "pipenv", "conda"],
                "default": "venv",
            },
            {
                "key": "formatter",
                "question": "Default Python formatter?",
                "options": ["black", "ruff", "none"],
                "default": "black",
            },
        ]

    # ── System introspection ────────────────────────────────────

    def introspect(self, project_path: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "python_path": sys.executable,
            "in_venv": sys.prefix != sys.base_prefix,
            "venv_path": sys.prefix if sys.prefix != sys.base_prefix else None,
            "site_packages": sysconfig.get_path("purelib"),
            "installed_packages": {},
            "pyenv_available": shutil.which("pyenv") is not None,
            "available_pythons": [],
        }

        # List all installed packages with versions
        for dist in importlib.metadata.distributions():
            name = dist.metadata["Name"]
            version = dist.metadata["Version"]
            result["installed_packages"][name.lower()] = version

        # Check for pyenv-managed Python versions
        if result["pyenv_available"]:
            try:
                proc = subprocess.run(
                    ["pyenv", "versions", "--bare"],
                    capture_output=True, text=True, timeout=5,
                )
                if proc.returncode == 0:
                    result["available_pythons"] = [
                        v.strip() for v in proc.stdout.strip().split("\n") if v.strip()
                    ]
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        # Read requirements.txt if it exists
        req_file = Path(project_path) / "requirements.txt"
        if req_file.exists():
            result["requirements_txt"] = req_file.read_text().strip().split("\n")

        # Read pyproject.toml dependencies if it exists
        pyproject = Path(project_path) / "pyproject.toml"
        if pyproject.exists():
            result["has_pyproject"] = True

        return result

    # ── Spec generation ─────────────────────────────────────────

    def build_spec(self, description: str, context: dict[str, Any]) -> dict[str, Any]:
        """Generate a Python env spec from description or template name."""
        # Simple keyword-based spec generation (no LLM needed)
        packages = self._parse_packages_from_description(description)

        # Determine a reasonable env_id
        words = re.findall(r'\w+', description.lower())
        env_id = f"py-{'-'.join(words[:3])}" if words else "py-default"

        # Detect Python version
        runtime = None
        version_match = re.search(r'python\s*(\d+\.\d+)', description, re.IGNORECASE)
        if version_match:
            runtime = version_match.group(1)

        introspection = context.get("introspection", {})

        return {
            "env_id": env_id,
            "module": "python",
            "runtime_version": runtime or f"{sys.version_info.major}.{sys.version_info.minor}",
            "packages": [{"name": p} for p in packages],
            "env_path": str(Path.home() / ".shellock" / "envs" / env_id),
            "reasoning": f"Parsed from description: '{description}'",
        }

    def validate_spec(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        """Cross-check spec against installed packages."""
        warnings = []
        introspection = self.introspect(spec.get("env_path", "."))
        installed = introspection.get("installed_packages", {})

        packages = spec.get("packages", [])
        for pkg in packages:
            name = pkg["name"] if isinstance(pkg, dict) else pkg
            name_lower = name.lower().split("[")[0].split(">")[0].split("<")[0].split("=")[0].split("~")[0]

            if name_lower in installed:
                warnings.append({
                    "level": "info",
                    "message": f"{name_lower} {installed[name_lower]} already installed globally",
                    "suggestion": "Will install into isolated venv",
                })

        # Check if the requested Python version is available
        runtime = spec.get("runtime_version")
        if runtime and introspection.get("pyenv_available"):
            available = introspection.get("available_pythons", [])
            if available and not any(runtime in v for v in available):
                warnings.append({
                    "level": "caution",
                    "message": f"Python {runtime} not found in pyenv. May need to install it.",
                    "suggestion": f"pyenv install {runtime}",
                })

        return warnings

    # ── Command dispatch ────────────────────────────────────────

    def dispatch(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        env_path = spec.get("env_path", ".venv")
        runtime = spec.get("runtime_version", "3")
        packages = spec.get("packages", [])

        commands = []

        # Create virtual environment
        python_cmd = f"python{runtime}" if runtime else "python3"
        commands.append({
            "command": f"{python_cmd} -m venv {env_path}",
            "impact": "safe",
            "description": f"Create virtual environment at {env_path}",
            "rollback_command": f"rm -rf {env_path}",
        })

        # Upgrade pip inside the venv
        pip_path = f"{env_path}/bin/pip"
        commands.append({
            "command": f"{pip_path} install --upgrade pip",
            "impact": "safe",
            "description": "Upgrade pip to latest version",
        })

        # Install packages
        if packages:
            pkg_names = []
            for p in packages:
                if isinstance(p, dict):
                    name = p.get("name", "")
                    version = p.get("version")
                    extras = p.get("extras", [])
                    pkg_str = name
                    if extras:
                        pkg_str += f"[{','.join(extras)}]"
                    if version:
                        pkg_str += version if version.startswith(("=", ">", "<", "~", "!")) else f"=={version}"
                    pkg_names.append(pkg_str)
                else:
                    pkg_names.append(str(p))

            commands.append({
                "command": f"{pip_path} install {' '.join(pkg_names)}",
                "impact": "safe",
                "description": f"Install: {', '.join(pkg_names)}",
                "rollback_command": f"{pip_path} uninstall -y {' '.join(pkg_names)}",
            })

        # Post hooks
        for hook in spec.get("post_hooks", []):
            commands.append({
                "command": f"{env_path}/bin/{hook}" if not hook.startswith("/") else hook,
                "impact": "caution",
                "description": f"Post-hook: {hook}",
            })

        return commands

    # ── Error handling ──────────────────────────────────────────

    def diagnose(self, stderr: str, context: dict[str, Any]) -> dict[str, Any] | None:
        """Diagnose using Python's introspection."""

        # ModuleNotFoundError
        match = re.search(r"ModuleNotFoundError: No module named ['\"](\w+)['\"]", stderr)
        if match:
            module_name = match.group(1)
            return self._diagnose_import_error(module_name)

        # Version conflict
        if "VersionConflict" in stderr or "dependency resolver" in stderr:
            return self._diagnose_version_conflict(stderr, context)

        # Externally managed environment (PEP 668)
        if "externally-managed-environment" in stderr:
            return {
                "action": "configure",
                "commands": ["python3 -m venv .venv", "source .venv/bin/activate"],
                "reasoning": "System Python is externally managed (PEP 668). Use a virtual environment instead.",
            }

        return None

    def handle_error(self, stderr: str, context: dict[str, Any]) -> dict[str, Any]:
        """Full error handling chain."""
        # Layer 1: Introspection
        result = self.diagnose(stderr, context)
        if result:
            result["method"] = "introspection"
            return result

        # Layer 2: Knowledge base patterns
        pattern = self.match_error_pattern(stderr)
        if pattern:
            pattern["method"] = "knowledge_base"
            return pattern

        # Layer 3: LLM (handled by the CLI layer, not the module)
        return {
            "diagnosed": False,
            "method": "unknown",
            "suggestions": [
                "Try running the command manually to see the full error",
                "Check if your virtual environment is activated",
            ],
        }

    # ── Private helpers ─────────────────────────────────────────

    def _diagnose_import_error(self, module_name: str) -> dict[str, Any]:
        """Use Python's own metadata to diagnose import failures."""
        try:
            version = importlib.metadata.version(module_name)
            # Installed but not importable — wrong env?
            return {
                "action": "configure",
                "commands": [],
                "reasoning": (
                    f"{module_name} {version} is installed but not importable. "
                    "You may be in the wrong virtual environment."
                ),
            }
        except importlib.metadata.PackageNotFoundError:
            pass

        # Not installed — suggest install
        result: dict[str, Any] = {
            "action": "install",
            "package": module_name,
            "commands": [f"pip install {module_name}"],
            "reasoning": f"{module_name} is not installed.",
        }

        # Did they mean something similar?
        all_packages = {
            d.metadata["Name"].lower()
            for d in importlib.metadata.distributions()
        }
        close = difflib.get_close_matches(module_name.lower(), list(all_packages), n=3)
        if close:
            result["did_you_mean"] = close

        return result

    def _diagnose_version_conflict(self, stderr: str, context: dict[str, Any]) -> dict[str, Any] | None:
        """Extract conflicting packages from pip resolver errors."""
        # Look for "X requires Y, but you have Z"
        conflicts = re.findall(
            r"(\S+)\s+requires\s+(\S+).*but you have\s+(\S+)\s+(\S+)",
            stderr,
        )
        if conflicts:
            fix_commands = []
            reasoning_parts = []
            for requirer, required, conflict_pkg, conflict_ver in conflicts:
                fix_commands.append(f"pip install --upgrade {conflict_pkg}")
                reasoning_parts.append(
                    f"{requirer} needs {required}, but {conflict_pkg} {conflict_ver} is installed"
                )
            return {
                "action": "upgrade",
                "commands": fix_commands,
                "reasoning": ". ".join(reasoning_parts),
            }
        return None

    def _parse_packages_from_description(self, description: str) -> list[str]:
        """Extract package names from a natural-language description."""
        # Known Python packages to look for
        known_packages = {
            "fastapi", "flask", "django", "uvicorn", "gunicorn",
            "requests", "httpx", "aiohttp",
            "numpy", "pandas", "scipy", "matplotlib", "seaborn",
            "scikit-learn", "sklearn", "tensorflow", "pytorch", "torch",
            "pydantic", "sqlalchemy", "alembic",
            "celery", "redis", "pytest", "black", "ruff", "mypy",
            "isort", "flake8", "pylint", "pre-commit",
            "jupyter", "notebook", "ipython",
            "pillow", "opencv-python", "beautifulsoup4", "scrapy",
            "click", "typer", "rich", "textual",
            "boto3", "google-cloud", "azure",
            "fastapi-users", "passlib", "python-jose",
            "streamlit", "gradio", "dash",
        }

        words = re.findall(r'[\w-]+', description.lower())
        found = []

        for word in words:
            if word in known_packages:
                found.append(word)
            # Handle sklearn → scikit-learn
            elif word == "sklearn":
                found.append("scikit-learn")

        return found if found else []
