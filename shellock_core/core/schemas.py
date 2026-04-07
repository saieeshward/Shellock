"""Pydantic models for Shellock.

These schemas are the system's source of truth.  Every piece of data
that flows through Shellock — environment specs, audit entries, user
profiles, error reports — is validated against these models.

All schemas include ``schema_version`` for forward-compatible migration.
Extra fields are forbidden (``model_config(extra='forbid')``) so LLM
output drift is caught immediately by Pydantic validation.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ── Enums ───────────────────────────────────────────────────────


class Impact(str, Enum):
    """Impact classification for commands shown in the approval screen."""

    SAFE = "safe"
    CAUTION = "caution"
    BLOCKED = "blocked"


class ActionType(str, Enum):
    """Types of actions recorded in the audit trail."""

    INIT = "init"
    FIX = "fix"
    ADD = "add"
    REMOVE = "remove"
    ROLLBACK = "rollback"


class DiagnosisMethod(str, Enum):
    """How an error was diagnosed — used in the audit trail."""

    INTROSPECTION = "introspection"
    KNOWLEDGE_BASE = "knowledge_base"
    LLM = "llm"
    UNKNOWN = "unknown"


class LLMTier(str, Enum):
    """LLM availability tier."""

    LOCAL = "local"
    CLOUD = "cloud"
    TEMPLATE = "template"


# ── Environment Spec ────────────────────────────────────────────


class PackageSpec(BaseModel):
    """A single package to install."""

    model_config = {"extra": "forbid"}

    name: str
    version: str | None = None
    extras: list[str] = Field(default_factory=list)

    def to_install_string(self) -> str:
        """Return pip/npm-style install string, e.g. 'fastapi>=0.100'."""
        base = self.name
        if self.extras:
            base += f"[{','.join(self.extras)}]"
        if self.version:
            base += self.version if self.version.startswith(("=", ">", "<", "~", "!")) else f"=={self.version}"
        return base


class EnvSpec(BaseModel):
    """The core environment specification.

    This is what the LLM generates, the user approves, and the
    dispatcher executes.  It must be human-readable and editable.
    """

    model_config = {"extra": "forbid"}

    schema_version: str = "1.0"
    env_id: str
    module: str
    session_name: str | None = None
    runtime_version: str | None = Field(
        default=None,
        description="e.g. '3.11' for Python, '20' for Node",
    )
    packages: list[PackageSpec] = Field(default_factory=list)
    env_vars: dict[str, str] = Field(default_factory=dict)
    post_hooks: list[str] = Field(default_factory=list)
    env_path: str | None = None
    reasoning: str | None = Field(
        default=None,
        description="LLM's explanation of its choices, shown on demand",
    )
    approved: bool = False
    created_at: datetime = Field(default_factory=datetime.now)


# ── Commands ────────────────────────────────────────────────────


class Command(BaseModel):
    """A single command to be executed by the dispatcher."""

    model_config = {"extra": "forbid"}

    command: str
    impact: Impact = Impact.SAFE
    description: str = ""
    rollback_command: str | None = Field(
        default=None,
        description="Command to undo this action, used by shellock rollback",
    )


# ── Audit Trail ─────────────────────────────────────────────────


class ActionEntry(BaseModel):
    """A single action recorded in the project's audit trail."""

    model_config = {"extra": "forbid"}

    id: str
    type: ActionType
    spec: dict[str, Any] | None = None
    commands_run: list[str] = Field(default_factory=list)
    rollback_commands: list[str] = Field(default_factory=list)
    result: str = ""
    failed_stderr: str | None = Field(
        default=None,
        description="Actual stderr output from a failed command, used by 'shellock fix'",
    )
    trigger_error: str | None = None
    error_fingerprint: str | None = None
    fix_applied: dict[str, Any] | None = None
    caused_by: str | None = Field(
        default=None,
        description="ID of the action that caused this error (cascading fix detection)",
    )
    diagnosis_method: DiagnosisMethod | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class ProjectHistory(BaseModel):
    """Per-project audit trail, stored in <project>/.shellock/history.json."""

    model_config = {"extra": "forbid"}

    schema_version: str = "1.0"
    project: str
    module: str | None = None
    actions: list[ActionEntry] = Field(default_factory=list)
    error_frequency: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Error fingerprint → {pattern, count, fixes_attempted, fixes_that_worked}",
    )
    compacted_at: datetime | None = None


# ── User Profile ────────────────────────────────────────────────


class SystemInfo(BaseModel):
    """Auto-detected system information, set during onboarding."""

    os: str = ""
    arch: str = ""
    shell: str = ""
    package_managers: list[str] = Field(default_factory=list)
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_tier: LLMTier = LLMTier.TEMPLATE
    cpu_info: str = Field(default="", description="CPU model or identifier")
    cpu_logical_cores: int | None = Field(default=None, description="Logical CPU cores")
    cpu_physical_cores: int | None = Field(default=None, description="Physical CPU cores, if known")
    gpu_info: str | None = Field(default=None, description="Detected GPU or accelerator")
    cuda_available: bool = Field(default=False, description="Is CUDA available via torch?")
    mps_available: bool = Field(default=False, description="Is Apple MPS available?")


class UserProfile(BaseModel):
    """Global user preferences, stored in ~/.shellock/profile.json.

    Preferences are deterministic counters — no LLM guessing.
    After ``suggestion_threshold`` uses, a tool is auto-suggested.
    """

    model_config = {"extra": "forbid"}

    schema_version: str = "1.0"
    system: SystemInfo = Field(default_factory=SystemInfo)
    preferences: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="Category → {tool: count}, e.g. {'formatter': {'black': 9, 'ruff': 3}}",
    )
    suggestion_threshold: int = 3
    rejected_suggestions: list[str] = Field(default_factory=list)
    onboarding_complete: bool = False
    created_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)

    def record_choice(self, category: str, tool: str) -> None:
        """Increment the usage counter for a tool in a category."""
        if category not in self.preferences:
            self.preferences[category] = {}
        self.preferences[category][tool] = self.preferences[category].get(tool, 0) + 1
        self.last_updated = datetime.now()

    def get_suggestions(self, category: str, exclude: list[str] | None = None) -> list[str]:
        """Return tools that have been used >= threshold times."""
        exclude = exclude or []
        counts = self.preferences.get(category, {})
        return [
            tool
            for tool, count in counts.items()
            if count >= self.suggestion_threshold
            and tool not in self.rejected_suggestions
            and tool not in exclude
        ]


# ── Error Diagnosis ─────────────────────────────────────────────


class DiagnosisResult(BaseModel):
    """Result of an error diagnosis attempt."""

    diagnosed: bool = False
    method: DiagnosisMethod = DiagnosisMethod.UNKNOWN
    fix: dict[str, Any] | None = None
    suggestions: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    error_fingerprint: str | None = None


# ── Shellock Config ─────────────────────────────────────────────


class ShelllockConfig(BaseModel):
    """Global Shellock configuration, stored in ~/.shellock/config.json."""

    schema_version: str = "1.0"
    llm_provider: str = "ollama"
    llm_model: str = "llama3.2:3b"
    llm_api_key: str | None = Field(default=None, description="Only for cloud providers")
    plain_mode: bool = Field(default=False, description="Disable Rich formatting")
    history_compaction_threshold: int = 200
