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
    cpu_info = _detect_cpu_model()
    logical_cores, physical_cores = _detect_cpu_counts()
    gpu_info, cuda_available, mps_available = _detect_accelerators()
    return SystemInfo(
        os=_detect_os(),
        arch=platform.machine(),
        shell=_detect_shell(),
        package_managers=_detect_package_managers(),
        llm_provider=_detect_llm_provider(),
        llm_model=_detect_llm_model(),
        llm_tier=_detect_llm_tier(),
        cpu_info=cpu_info,
        cpu_logical_cores=logical_cores,
        cpu_physical_cores=physical_cores,
        gpu_info=gpu_info,
        cuda_available=cuda_available,
        mps_available=mps_available,
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
                # Skip header, skip embedding-only models (can't do generation)
                for line in lines[1:]:
                    parts = line.split()
                    if not parts:
                        continue
                    model_name = parts[0]
                    if "embed" not in model_name.lower():
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


def _detect_cpu_model() -> str:
    """Try to report the CPU brand string."""
    if sys.platform == "darwin":
        # Intel Mac: brand string is in machdep.cpu.brand_string
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        # Apple Silicon: use hw.model (e.g. "Apple M2 Pro")
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.model"],
                capture_output=True, text=True, timeout=2,
            )
            model = result.stdout.strip()
            if result.returncode == 0 and model:
                # hw.model gives e.g. "Mac14,3"; try system_profiler for human name
                sp = subprocess.run(
                    ["system_profiler", "SPHardwareDataType"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in sp.stdout.splitlines():
                    if "Chip:" in line or "Processor Name:" in line:
                        return line.split(":", 1)[1].strip()
                return model
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    elif sys.platform.startswith("linux"):
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except FileNotFoundError:
            pass
    elif os.name == "nt":
        # Try registry first — works on all modern Windows without wmic
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            winreg.CloseKey(key)
            if name and name.strip():
                return name.strip()
        except Exception:
            pass
        # wmic fallback (deprecated on Windows 11 but may still work)
        try:
            result = subprocess.run(
                ["wmic", "cpu", "get", "name"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if len(lines) >= 2:
                return lines[1]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return platform.processor() or "unknown"


def _detect_cpu_counts() -> tuple[int | None, int | None]:
    """Return logical and physical core counts when available."""
    logical = os.cpu_count()
    physical = None
    try:
        import psutil

        physical = psutil.cpu_count(logical=False)
    except ImportError:
        if sys.platform.startswith("linux"):
            physical = _count_physical_cores_linux()
    except Exception:
        physical = None
    return logical or None, physical


def _count_physical_cores_linux() -> int | None:
    """Parse /proc/cpuinfo for physical CPU IDs."""
    try:
        physical_ids = set()
        with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                if key.strip().lower() == "physical id":
                    physical_ids.add(value.strip())
        if physical_ids:
            return len(physical_ids)
    except FileNotFoundError:
        pass
    return None


def _detect_accelerators() -> tuple[str | None, bool, bool]:
    """Detect GPU hardware and accelerator availability."""
    gpu_info: str | None = None
    cuda_available = False
    mps_available = False

    try:
        import torch

        cuda_available = getattr(torch.cuda, "is_available", lambda: False)()
        mps_available = getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available()
        if cuda_available:
            names: list[str] = []
            for idx in range(getattr(torch.cuda, "device_count", lambda: 0)()):
                try:
                    names.append(torch.cuda.get_device_name(idx))
                except Exception:
                    pass
            if names:
                # preserve order without duplicates
                seen = []
                for name in names:
                    if name not in seen:
                        seen.append(name)
                gpu_info = ", ".join(seen)
        elif mps_available:
            gpu_info = "Apple MPS"
    except Exception:
        pass

    if not gpu_info:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
                if names:
                    gpu_info = ", ".join(dict.fromkeys(names))
                    cuda_available = True
        except Exception:
            pass

    # MPS fallback: Apple Silicon without torch installed
    if not mps_available and sys.platform == "darwin" and platform.machine() == "arm64":
        mps_available = True
        if not gpu_info:
            gpu_info = "Apple MPS"

    return gpu_info, cuda_available, mps_available
