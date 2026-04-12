"""Registry — audit trail and project history management.

Handles reading/writing per-project history files and the global
user profile.  All state is human-readable JSON on disk.

File layout:
    ~/.shellock/
    ├── profile.json          # global user preferences
    ├── config.json           # shellock configuration
    └── knowledge/
        └── learned.json      # cross-project learned error patterns

    <project>/.shellock/
    ├── spec.json             # current active environment spec
    └── history.json          # ordered actions for this project
"""

from __future__ import annotations

import hashlib
import sys as _sys
if _sys.platform != "win32":
    import fcntl as _fcntl
else:
    _fcntl = None
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from shellock_core.core.schemas import (
    ActionEntry,
    ActionType,
    DiagnosisMethod,
    EnvSpec,
    ProjectHistory,
    ShelllockConfig,
    UserProfile,
)

logger = logging.getLogger(__name__)

SHELLOCK_HOME = Path.home() / ".shellock"
PROFILE_PATH = SHELLOCK_HOME / "profile.json"
CONFIG_PATH = SHELLOCK_HOME / "config.json"
KNOWLEDGE_PATH = SHELLOCK_HOME / "knowledge"
LEARNED_FIXES_PATH = SHELLOCK_HOME / "knowledge" / "learned.json"

def ensure_shellock_home() -> Path:
    """Create ~/.shellock/ if it doesn't exist."""
    SHELLOCK_HOME.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE_PATH.mkdir(exist_ok=True)

    if not LEARNED_FIXES_PATH.exists():
        _write_json(LEARNED_FIXES_PATH, {"schema_version": "1.0", "fixes": {}})

    return SHELLOCK_HOME

def ensure_project_dir(project_path: str) -> Path:
    """Create <project>/.shellock/ if it doesn't exist."""
    shellock_dir = Path(project_path) / ".shellock"
    shellock_dir.mkdir(parents=True, exist_ok=True)
    return shellock_dir


# ── Profile ─────────────────────────────────────────────────────


def load_profile() -> UserProfile:
    """Load the global user profile, creating a default if missing."""
    ensure_shellock_home()
    if PROFILE_PATH.exists():
        try:
            data = json.loads(PROFILE_PATH.read_text())
            return UserProfile.model_validate(data)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Corrupted profile.json: %s — backing up and starting fresh", e)
            _backup_corrupted(PROFILE_PATH)
    return UserProfile()


def save_profile(profile: UserProfile) -> None:
    """Save the global user profile."""
    ensure_shellock_home()
    profile.last_updated = datetime.now()
    _write_json(PROFILE_PATH, profile.model_dump(mode="json"))


# ── Config ──────────────────────────────────────────────────────


def load_config() -> ShelllockConfig:
    """Load Shellock configuration."""
    ensure_shellock_home()
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
            return ShelllockConfig.model_validate(data)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Corrupted config.json: %s — backing up and starting fresh", e)
            _backup_corrupted(CONFIG_PATH)
    return ShelllockConfig()


def save_config(config: ShelllockConfig) -> None:
    """Save Shellock configuration."""
    ensure_shellock_home()
    _write_json(CONFIG_PATH, config.model_dump(mode="json"))

# ── Learned fixes ──────────────────────────────────────────────

def load_learned_fixes() -> dict[str, Any]:
    """Load globally learned successful fixes."""
    ensure_shellock_home()
    if LEARNED_FIXES_PATH.exists():
        try:
            return json.loads(LEARNED_FIXES_PATH.read_text())
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Corrupted learned.json: %s — backing up and starting fresh", e)
            _backup_corrupted(LEARNED_FIXES_PATH)
    return {"schema_version": "1.0", "fixes": {}}


def record_successful_fix(
    error_fingerprint: str,
    error_text: str,
    fix_applied: dict[str, Any],
    module_name: str | None = None,
    project_path: str | None = None,
    diagnosis_method: DiagnosisMethod | None = None,
) -> None:
    """Record a successful fix into the global learned fixes store."""
    data = load_learned_fixes()
    fixes = data.setdefault("fixes", {})

    key = f"{module_name or 'any'}::{error_fingerprint}"

    entry = fixes.setdefault(
        key,
        {
            "error_fingerprint": error_fingerprint,
            "module": module_name or "any",
            "pattern": error_text[:200],
            "count": 0,
            "fix": fix_applied,
            "project_path": project_path,
            "diagnosis_method": diagnosis_method.value if diagnosis_method else None,
            "recorded_at": None,
            "successful_fixes": [],
        },
    )

    entry["count"] += 1
    entry["pattern"] = error_text[:200]
    entry["fix"] = fix_applied
    entry["project_path"] = project_path
    entry["diagnosis_method"] = diagnosis_method.value if diagnosis_method else None
    entry["recorded_at"] = datetime.now().isoformat()

    fix_record = {
        "fix": fix_applied,
        "module": module_name or "any",
        "project_path": project_path,
        "diagnosis_method": diagnosis_method.value if diagnosis_method else None,
        "recorded_at": datetime.now().isoformat(),
    }

    fix_key = json.dumps(
        {
            "fix": fix_record["fix"],
            "module": fix_record["module"],
            "diagnosis_method": fix_record["diagnosis_method"],
        },
        sort_keys=True,
        default=str,
    )

    existing_keys = {
        json.dumps(
            {
                "fix": item.get("fix"),
                "module": item.get("module"),
                "diagnosis_method": item.get("diagnosis_method"),
            },
            sort_keys=True,
            default=str,
        )
        for item in entry["successful_fixes"]
    }

    if fix_key not in existing_keys:
        entry["successful_fixes"].append(fix_record)

    _write_json(LEARNED_FIXES_PATH, data)


def get_learned_fix(
    error_fingerprint: str,
    module_name: str | None = None,
) -> dict[str, Any] | None:
    """Return a previously successful fix for this fingerprint/module, if any."""
    data = load_learned_fixes()
    fixes = data.get("fixes", {})

    if module_name:
        key = f"{module_name}::{error_fingerprint}"
        entry = fixes.get(key)
        if entry and isinstance(entry.get("fix"), dict):
            return entry["fix"]

    key = f"any::{error_fingerprint}"
    entry = fixes.get(key)
    if entry and isinstance(entry.get("fix"), dict):
        return entry["fix"]

    return None

# ── Project history ─────────────────────────────────────────────


def load_history(project_path: str) -> ProjectHistory:
    """Load the project's action history."""
    history_file = Path(project_path) / ".shellock" / "history.json"
    if history_file.exists():
        try:
            data = json.loads(history_file.read_text())
            return ProjectHistory.model_validate(data)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Corrupted history.json: %s — backing up and starting fresh", e)
            _backup_corrupted(history_file)
    return ProjectHistory(project=str(Path(project_path).resolve()))


def save_history(project_path: str, history: ProjectHistory) -> None:
    """Save the project's action history with file locking."""
    shellock_dir = ensure_project_dir(project_path)
    history_file = shellock_dir / "history.json"
    _write_json(history_file, history.model_dump(mode="json"))


def record_action(
    project_path: str,
    action_type: ActionType,
    spec: dict[str, Any] | None = None,
    commands_run: list[str] | None = None,
    rollback_commands: list[str] | None = None,
    result: str = "success",
    failed_stderr: str | None = None,
    trigger_error: str | None = None,
    error_fingerprint: str | None = None,
    fix_applied: dict[str, Any] | None = None,
    caused_by: str | None = None,
    diagnosis_method: DiagnosisMethod | None = None,
) -> str:
    """Record an action in the project history. Returns the action ID."""
    history = load_history(project_path)

    action_id = f"act-{uuid.uuid4().hex[:6]}"
    entry = ActionEntry(
        id=action_id,
        type=action_type,
        spec=spec,
        commands_run=commands_run or [],
        rollback_commands=rollback_commands or [],
        result=result,
        failed_stderr=failed_stderr,
        trigger_error=trigger_error,
        error_fingerprint=error_fingerprint,
        fix_applied=fix_applied,
        caused_by=caused_by,
        diagnosis_method=diagnosis_method,
    )

    history.actions.append(entry)

    # Update error frequency tracking
    if error_fingerprint and trigger_error:
        _update_error_frequency(history, error_fingerprint, trigger_error, fix_applied)

    # Compact if needed
    if len(history.actions) > 200:
        _compact_history(project_path, history)

    save_history(project_path, history)
    return action_id


def get_recent_actions(project_path: str, n: int = 5) -> list[dict[str, Any]]:
    """Get the last N actions for LLM context."""
    history = load_history(project_path)
    recent = history.actions[-n:]
    return [a.model_dump(mode="json") for a in recent]


def check_cascading_error(
    project_path: str,
    error_fingerprint: str,
    window_minutes: int = 10,
) -> str | None:
    """Check if this error was likely caused by a recent fix.

    Returns the causing action ID, or None.
    """
    history = load_history(project_path)
    now = datetime.now()

    # Look at recent fix actions
    for action in reversed(history.actions[-10:]):
        if action.type != ActionType.FIX:
            continue
        age = (now - action.timestamp).total_seconds() / 60
        if age <= window_minutes:
            return action.id

    return None


# ── Spec management ─────────────────────────────────────────────


def save_spec(project_path: str, spec: EnvSpec) -> None:
    """Save the active environment spec."""
    shellock_dir = ensure_project_dir(project_path)
    spec_file = shellock_dir / "spec.json"
    _write_json(spec_file, spec.model_dump(mode="json"))


def load_spec(project_path: str) -> EnvSpec | None:
    """Load the active environment spec, if any."""
    spec_file = Path(project_path) / ".shellock" / "spec.json"
    if spec_file.exists():
        data = json.loads(spec_file.read_text())
        return EnvSpec.model_validate(data)
    return None


# ── Error fingerprinting ───────────────────────────────────────


def fingerprint_error(stderr: str) -> str:
    """Generate a stable fingerprint for an error.

    Strips variable parts (line numbers, timestamps, file paths)
    so the same root error always produces the same fingerprint.
    """
    normalized = stderr.strip()
    # Strip line numbers
    normalized = re.sub(r"line \d+", "line N", normalized)
    # Strip file paths (Unix and Windows)
    normalized = re.sub(r"/[\w/\-.]+/", "/.../", normalized)
    normalized = re.sub(r"[A-Za-z]:\\[\w\\\-. ]+\\", r"...\\", normalized)
    # Strip timestamps
    normalized = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", "TIMESTAMP", normalized)
    # Extract core error class if present
    error_match = re.search(r"(\w+Error|\w+Exception|\w+Warning):\s*(.+?)$", normalized, re.MULTILINE)
    if error_match:
        normalized = f"{error_match.group(1)}: {error_match.group(2)}"

    return hashlib.md5(normalized.encode()).hexdigest()[:8]


# ── Snapshots ──────────────────────────────────────────────────


def save_snapshot(env_path: str, label: str = "pre-fix") -> Path | None:
    """Save a snapshot of the environment's installed packages before a fix."""
    import shutil
    import subprocess as _sp

    env = Path(env_path)
    if not env.is_dir():
        return None

    # Disk space guard: warn if less than 500MB free
    try:
        stat = shutil.disk_usage(str(SHELLOCK_HOME))
        free_mb = stat.free / (1024 * 1024)
        if free_mb < 500:
            logger.warning("Low disk space: %.0fMB free. Pruning old snapshots.", free_mb)
            _prune_old_snapshots(30)  # prune snapshots older than 30 days
    except Exception:
        pass

    snapshots_dir = SHELLOCK_HOME / "snapshots" / env.name
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    snap_file = snapshots_dir / f"{label}-{ts}.json"

    snapshot: dict[str, Any] = {"timestamp": ts, "label": label, "env": str(env)}

    # Try pip freeze
    pip_path = env / "bin" / "pip"
    if not pip_path.exists():
        pip_path = env / "Scripts" / "pip.exe"
    if pip_path.exists():
        try:
            result = _sp.run(
                [str(pip_path), "freeze"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                snapshot["pip_freeze"] = result.stdout.strip().split("\n")
        except Exception:
            pass

    # Try npm ls
    pkg_json = env / "package.json"
    if pkg_json.exists():
        try:
            result = _sp.run(
                ["npm", "ls", "--json", "--depth=0"],
                capture_output=True, text=True, timeout=15, cwd=str(env),
            )
            if result.returncode == 0:
                snapshot["npm_ls"] = json.loads(result.stdout)
        except Exception:
            pass

    _write_json(snap_file, snapshot)
    return snap_file


# ── Lock files ─────────────────────────────────────────────────


def write_lock_file(env_path: str, module_name: str) -> Path | None:
    """Write a lock file capturing exact installed versions."""
    import subprocess as _sp

    env = Path(env_path)
    if not env.is_dir():
        return None

    lock_file = env / "shellock.lock"
    lock_data: dict[str, Any] = {
        "locked_at": datetime.now().isoformat(),
        "module": module_name,
        "packages": {},
    }

    if module_name == "python":
        pip_path = env / "bin" / "pip"
        if not pip_path.exists():
            pip_path = env / "Scripts" / "pip.exe"
        if pip_path.exists():
            try:
                result = _sp.run(
                    [str(pip_path), "freeze"],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split("\n"):
                        if "==" in line:
                            name, ver = line.split("==", 1)
                            lock_data["packages"][name] = ver
            except Exception:
                pass
    elif module_name == "node":
        try:
            result = _sp.run(
                ["npm", "ls", "--json", "--depth=0"],
                capture_output=True, text=True, timeout=15, cwd=str(env),
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for name, info in data.get("dependencies", {}).items():
                    lock_data["packages"][name] = info.get("version", "unknown")
        except Exception:
            pass

    _write_json(lock_file, lock_data)
    return lock_file


# ── Security scanning ──────────────────────────────────────────


def run_security_scan(env_path: str, module_name: str) -> dict[str, Any]:
    """Run pip-audit or npm audit and return results."""
    import shutil
    import subprocess as _sp

    results: dict[str, Any] = {"scanned": False, "vulnerabilities": [], "tool": None}

    if module_name == "python":
        pip_path = Path(env_path) / "bin" / "pip"
        if not pip_path.exists():
            pip_path = Path(env_path) / "Scripts" / "pip.exe"

        # Try pip-audit first
        if shutil.which("pip-audit"):
            results["tool"] = "pip-audit"
            try:
                result = _sp.run(
                    ["pip-audit", "--format=json", f"--python={pip_path.parent / 'python'}"],
                    capture_output=True, text=True, timeout=60,
                )
                results["scanned"] = True
                if result.returncode != 0 and result.stdout:
                    vulns = json.loads(result.stdout)
                    results["vulnerabilities"] = vulns
            except Exception:
                pass
        else:
            # Fallback: pip check for broken deps
            results["tool"] = "pip-check"
            try:
                result = _sp.run(
                    [str(pip_path), "check"],
                    capture_output=True, text=True, timeout=30,
                )
                results["scanned"] = True
                if result.returncode != 0:
                    results["vulnerabilities"] = [{"issue": line} for line in result.stdout.strip().split("\n") if line]
            except Exception:
                pass

    elif module_name == "node":
        results["tool"] = "npm-audit"
        try:
            result = _sp.run(
                ["npm", "audit", "--json"],
                capture_output=True, text=True, timeout=60,
                cwd=env_path,
            )
            results["scanned"] = True
            if result.stdout:
                audit_data = json.loads(result.stdout)
                vulns = audit_data.get("vulnerabilities", {})
                results["vulnerabilities"] = [
                    {"name": name, "severity": info.get("severity", "unknown")}
                    for name, info in vulns.items()
                ]
        except Exception:
            pass

    return results


# ── Private helpers ─────────────────────────────────────────────


def _prune_old_snapshots(max_age_days: int = 30) -> int:
    """Remove snapshots older than max_age_days. Returns count of pruned files."""
    snapshots_dir = SHELLOCK_HOME / "snapshots"
    if not snapshots_dir.is_dir():
        return 0
    pruned = 0
    now = datetime.now()
    for snap_file in snapshots_dir.rglob("*.json"):
        try:
            age_days = (now - datetime.fromtimestamp(snap_file.stat().st_mtime)).days
            if age_days > max_age_days:
                snap_file.unlink()
                pruned += 1
        except Exception:
            pass
    if pruned:
        logger.info("Pruned %d old snapshots (>%d days)", pruned, max_age_days)
    return pruned


def _backup_corrupted(path: Path) -> None:
    """Back up a corrupted file to <filename>.bak and remove the original."""
    bak = path.with_suffix(path.suffix + ".bak")
    try:
        import shutil
        shutil.copy2(path, bak)
        path.unlink()
        logger.info("Backed up corrupted %s to %s", path.name, bak.name)
    except Exception as e:
        logger.error("Failed to backup corrupted file: %s", e)


def _update_error_frequency(
    history: ProjectHistory,
    fingerprint: str,
    error_text: str,
    fix_applied: dict[str, Any] | None,
) -> None:
    """Track how often an error occurs and which fixes work."""
    if fingerprint not in history.error_frequency:
        history.error_frequency[fingerprint] = {
            "pattern": error_text[:100],
            "count": 0,
            "fixes_attempted": [],
            "fixes_that_worked": [],
        }

    entry = history.error_frequency[fingerprint]
    entry["count"] += 1

    if fix_applied:
        fix_summary = json.dumps(fix_applied, sort_keys=True)
        if fix_summary not in entry["fixes_attempted"]:
            entry["fixes_attempted"].append(fix_summary)


def _compact_history(project_path: str, history: ProjectHistory) -> None:
    """Archive old entries, keeping only the last 100."""
    archive_path = Path(project_path) / ".shellock" / "history.archive.json"

    # Load existing archive
    archive = []
    if archive_path.exists():
        archive = json.loads(archive_path.read_text())

    # Move old entries to archive
    to_archive = history.actions[:-100]
    archive.extend([a.model_dump(mode="json") for a in to_archive])
    _write_json(archive_path, archive)

    # Keep only recent entries
    history.actions = history.actions[-100:]
    history.compacted_at = datetime.now()

    logger.info("Compacted history: archived %d entries", len(to_archive))


def _write_json(path: Path, data: Any) -> None:
    """Write JSON with file locking for concurrency safety (Unix) or simple write (Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, default=str) + "\n"

    if _fcntl is not None:
        with open(path, "w") as f:
            try:
                _fcntl.flock(f.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                f.write(content)
                _fcntl.flock(f.fileno(), _fcntl.LOCK_UN)
            except BlockingIOError:
                import time
                for _ in range(50):
                    time.sleep(0.1)
                    try:
                        _fcntl.flock(f.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                        f.write(content)
                        _fcntl.flock(f.fileno(), _fcntl.LOCK_UN)
                        return
                    except BlockingIOError:
                        continue
                logger.error("Could not acquire lock on %s after 5s", path)
                raise
    else:
        # Windows: no file locking (single-user CLI, low concurrency risk)
        path.write_text(content)
