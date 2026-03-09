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


def ensure_shellock_home() -> Path:
    """Create ~/.shellock/ if it doesn't exist."""
    SHELLOCK_HOME.mkdir(parents=True, exist_ok=True)
    (SHELLOCK_HOME / "knowledge").mkdir(exist_ok=True)
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
        data = json.loads(PROFILE_PATH.read_text())
        return UserProfile.model_validate(data)
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
        data = json.loads(CONFIG_PATH.read_text())
        return ShelllockConfig.model_validate(data)
    return ShelllockConfig()


def save_config(config: ShelllockConfig) -> None:
    """Save Shellock configuration."""
    ensure_shellock_home()
    _write_json(CONFIG_PATH, config.model_dump(mode="json"))


# ── Project history ─────────────────────────────────────────────


def load_history(project_path: str) -> ProjectHistory:
    """Load the project's action history."""
    history_file = Path(project_path) / ".shellock" / "history.json"
    if history_file.exists():
        data = json.loads(history_file.read_text())
        return ProjectHistory.model_validate(data)
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


# ── Private helpers ─────────────────────────────────────────────


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
