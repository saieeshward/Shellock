"""System and project context detection.

Detects OS, architecture, available tools, installed LLMs, and
project-level cues.  All detection is deterministic — no LLM calls.
Results are used to enrich LLM prompts and drive module selection.
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from shellock_core.core.schemas import LLMTier, SystemInfo


def detect_system() -> SystemInfo:
    """Detect the current system's capabilities."""
    return SystemInfo(
        os=_detect_os(),
        arch=platform.machine(),
        shell=_detect_shell(),
        package_managers=_detect_package_managers(),
        llm_provider=_detect_llm_provider(),
        llm_model=_detect_llm_model(),
        llm_tier=_detect_llm_tier(),
    )


def detect_project_context(project_path: str) -> dict[str, Any]:
    """Read project-level cues from the filesystem.

    Returns a dict of detected signals (files found, inferred
    project type, existing environments, etc.).
    """
    path = Path(project_path)
    context: dict[str, Any] = {
        "path": str(path.resolve()),
        "files": [],
        "detected_modules": [],
        "existing_env": None,
    }

    # Check for known project files
    project_indicators = {
        "requirements.txt": "python",
        "pyproject.toml": "python",
        "Pipfile": "python",
        "setup.py": "python",
        "setup.cfg": "python",
        "package.json": "node",
        ".nvmrc": "node",
        "Dockerfile": "docker",
        "docker-compose.yml": "docker",
        "docker-compose.yaml": "docker",
        "Cargo.toml": "rust",
        "go.mod": "go",
        "Gemfile": "ruby",
    }

    for filename, module in project_indicators.items():
        if (path / filename).exists():
            context["files"].append(filename)
            if module not in context["detected_modules"]:
                context["detected_modules"].append(module)

    # Check for existing virtual environments
    venv_paths = [".venv", "venv", "env", ".env"]
    for venv_dir in venv_paths:
        venv_path = path / venv_dir
        if venv_path.is_dir() and (venv_path / "bin" / "python").exists():
            context["existing_env"] = str(venv_path)
            break
        # Windows check
        if venv_path.is_dir() and (venv_path / "Scripts" / "python.exe").exists():
            context["existing_env"] = str(venv_path)
            break

    # Check for existing Shellock config
    shellock_dir = path / ".shellock"
    if shellock_dir.is_dir():
        context["shellock_initialized"] = True
        spec_file = shellock_dir / "spec.json"
        if spec_file.exists():
            context["has_active_spec"] = True

    return context


# ── Private helpers ─────────────────────────────────────────────


def _detect_os() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    return system  # "linux", "windows"


def _detect_shell() -> str:
    shell = os.environ.get("SHELL", "")
    if shell:
        return Path(shell).name  # "zsh", "bash", "fish"
    # Windows fallback
    comspec = os.environ.get("COMSPEC", "")
    if "powershell" in comspec.lower() or "pwsh" in comspec.lower():
        return "powershell"
    if comspec:
        return "cmd"
    return "unknown"


def _detect_package_managers() -> list[str]:
    managers = []
    candidates = ["brew", "apt", "dnf", "yum", "pacman", "pip", "pip3",
                   "npm", "yarn", "pnpm", "cargo", "go", "gem",
                   "conda", "pipx", "pyenv", "nvm"]
    for mgr in candidates:
        if shutil.which(mgr):
            managers.append(mgr)
    return managers


def _detect_llm_provider() -> str | None:
    """Check for running local LLM services."""
    # Ollama — default port 11434
    if _check_port(11434):
        return "ollama"
    # LM Studio — default port 1234
    if _check_port(1234):
        return "lm-studio"
    # llama.cpp server
    if shutil.which("llama-server") or shutil.which("llama-cli"):
        return "llama.cpp"
    return None


def _detect_llm_model() -> str | None:
    """Try to get the default model from the detected LLM provider."""
    provider = _detect_llm_provider()
    if provider == "ollama":
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if len(lines) > 1:
                    # First model listed (skip header)
                    model_name = lines[1].split()[0]
                    return model_name
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return None


def _detect_llm_tier() -> LLMTier:
    """Determine the best available LLM tier."""
    if _detect_llm_provider():
        return LLMTier.LOCAL
    if _has_internet():
        return LLMTier.CLOUD
    return LLMTier.TEMPLATE


def _check_port(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """Check if a service is listening on a port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def _has_internet(host: str = "1.1.1.1", port: int = 443, timeout: float = 2.0) -> bool:
    """Quick check for internet connectivity."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False
