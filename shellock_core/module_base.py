"""Base interface for all Shellock ecosystem modules.

Every module (Python, Node, Docker, etc.) implements this interface.
The core never knows ecosystem-specific details — modules handle that.

The resolution order for errors is:
    1. Module.diagnose()       — system introspection (instant, accurate)
    2. Module.error_patterns   — built-in knowledge base (fast, offline)
    3. LLM with full context   — smart but slower, may hallucinate
    4. "I don't know"          — honest fallback with resource links
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class ShellockModule(ABC):
    """Base class for all Shellock ecosystem modules.

    Subclasses must define class-level attributes and implement all
    abstract methods. Each module is self-contained: it carries its
    own detection logic, command allowlist, error knowledge, and
    system introspection capabilities.
    """

    # ── Class attributes (set by subclass) ──────────────────────

    name: str
    """Short identifier, e.g. 'python', 'node', 'docker'."""

    description: str
    """One-line description shown in module listings."""

    triggers: list[str]
    """File patterns that indicate this module applies.
    e.g. ['requirements.txt', 'pyproject.toml', 'Pipfile']
    """

    allowed_commands: list[str]
    """Allowlist of command prefixes this module can execute.
    e.g. ['pip install', 'python -m venv', 'pyenv install']
    Anything not in this list is rejected before the user sees it.
    """

    blocked_patterns: list[str]
    """Regex patterns that are always rejected.
    e.g. [r'sudo\\s+', r'rm\\s+-rf', r'chmod\\s+777']
    """

    suggestable_tools: list[str]
    """Tools that can be auto-suggested after repeated use.
    e.g. ['black', 'ruff', 'pytest', 'mypy']
    """

    # ── Detection ───────────────────────────────────────────────

    @abstractmethod
    def detect(self, project_path: str) -> bool:
        """Return True if this module applies to the project at *project_path*.

        Checks for trigger files (requirements.txt, package.json, etc.)
        and any other ecosystem indicators.
        """

    # ── Onboarding ──────────────────────────────────────────────

    @abstractmethod
    def onboarding_questions(self) -> list[dict[str, Any]]:
        """Return module-specific setup questions for first run.

        Each dict has:
            key:      preference key stored in profile.json
            question: human-readable question text
            options:  list of valid choices
            default:  default choice if user presses Enter

        Example::

            [{"key": "python_env",
              "question": "Preferred environment tool?",
              "options": ["venv", "pipenv", "conda"],
              "default": "venv"}]
        """

    # ── System introspection ────────────────────────────────────

    @abstractmethod
    def introspect(self, project_path: str) -> dict[str, Any]:
        """Query actual system state without LLM or internet.

        Returns information about what is already installed, versions,
        paths, and any detected issues. This data enriches the approval
        screen and the LLM prompt.
        """

    # ── Spec generation ─────────────────────────────────────────

    @abstractmethod
    def build_spec(self, description: str, context: dict[str, Any]) -> dict[str, Any]:
        """Generate an environment spec fragment from user intent.

        *description* is the user's natural-language request.
        *context* contains system info, user preferences, and
        introspection results.

        The returned dict is merged into the full ShelllockEnvSpec.
        """

    @abstractmethod
    def validate_spec(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        """Cross-check a spec against actual system state.

        Uses introspection (not LLM) to verify that versions exist,
        dependencies don't conflict, and paths are valid.

        Returns a list of warnings/errors::

            [{"level": "caution",
              "message": "pydantic 1.10 installed, spec wants >=2.0",
              "suggestion": "Will upgrade pydantic"}]
        """

    # ── Command dispatch ────────────────────────────────────────

    @abstractmethod
    def dispatch(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert an approved spec into an ordered list of commands.

        Each command dict has::

            {"command": "pip install fastapi",
             "impact": "safe",       # safe | caution | blocked
             "description": "Install fastapi into the virtual environment"}

        Commands are checked against allowed_commands and blocked_patterns
        by the core dispatcher — modules don't need to re-check.
        """

    # ── Error handling ──────────────────────────────────────────

    @abstractmethod
    def diagnose(self, stderr: str, context: dict[str, Any]) -> dict[str, Any] | None:
        """Try to diagnose an error using system introspection alone.

        This is the fastest, most accurate error resolution path.
        Returns a fix proposal dict if the error is diagnosable,
        or None if introspection can't determine the cause.
        """

    @abstractmethod
    def handle_error(self, stderr: str, context: dict[str, Any]) -> dict[str, Any]:
        """Full error handling: introspection → knowledge base → LLM.

        Always returns a result, even if it's 'I don't know'.
        The returned dict has::

            {"diagnosed": True/False,
             "method": "introspection" | "knowledge_base" | "llm" | "unknown",
             "fix": {...} or None,
             "suggestions": [...],
             "resources": [...]}
        """

    # ── Knowledge base ──────────────────────────────────────────

    def load_error_patterns(self) -> list[dict[str, Any]]:
        """Load built-in error patterns from this module's knowledge dir.

        Override if patterns are stored differently. Default implementation
        looks for a ``knowledge/errors.json`` file next to the module.
        """
        import json

        knowledge_dir = Path(__file__).parent / "modules" / self.name / "knowledge"
        errors_file = knowledge_dir / "errors.json"
        if errors_file.exists():
            return json.loads(errors_file.read_text())
        return []

    def match_error_pattern(self, stderr: str) -> dict[str, Any] | None:
        """Match stderr against built-in error patterns.

        Returns the first matching pattern with its fix, or None.
        """
        import re

        for pattern in self.load_error_patterns():
            if re.search(pattern["match"], stderr, re.IGNORECASE):
                result = {
                    "pattern": pattern["match"],
                    "fix": pattern.get("fix", ""),
                    "docs": pattern.get("docs", ""),
                }
                # Extract dynamic values if the pattern has capture groups
                if "extract" in pattern:
                    match = re.search(pattern["extract"], stderr)
                    if match:
                        result["extracted"] = match.groups()
                return result
        return None
