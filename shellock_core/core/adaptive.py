"""Adaptive behaviour engine — the three axes of adaptation.

Every adaptive decision is announced visibly in the terminal so the
user can see *why* Shellock is doing what it's doing.  This makes
Shellock a scrutable adaptive application.

Three axes:
    1. User preferences  — learned from repeated tool choices
    2. Error patterns     — learned from past failures and fixes
    3. System context     — detected environment capabilities
"""

from __future__ import annotations

from typing import Any

from shellock_core.core import registry, ui
from shellock_core.core.schemas import UserProfile


# ── Axis 1: User Preferences ──────────────────────────────────


def suggest_from_preferences(
    profile: UserProfile,
    category: str,
    current_packages: list[str],
) -> list[str]:
    """Suggest tools the user has picked often before.

    Returns a list of package names to suggest, printing an
    adaptation announcement for each.
    """
    suggestions = profile.get_suggestions(category, exclude=current_packages)
    for tool in suggestions:
        count = profile.preferences.get(category, {}).get(tool, 0)
        ui.show_adaptive(
            axis="preferences",
            message=f"You've used '{tool}' {count} times before — adding it automatically.",
        )
    return suggestions


# ── Axis 2: Error Patterns ────────────────────────────────────


def check_known_errors(
    project_path: str,
    error_fingerprint: str,
) -> dict[str, Any] | None:
    """Check if we've seen this error before and have a known fix.

    Returns the fix dict if a previously successful fix is found,
    printing an adaptation announcement.
    """
    history = registry.load_history(project_path)
    freq = history.error_frequency.get(error_fingerprint, {})
    fixes_that_worked = freq.get("fixes_that_worked", [])

    if fixes_that_worked:
        import json
        fix = json.loads(fixes_that_worked[-1])
        count = freq.get("count", 0)
        ui.show_adaptive(
            axis="error-patterns",
            message=(
                f"This error has occurred {count} times. "
                f"Reusing a fix that worked before."
            ),
        )
        return fix
    return None


def announce_error_escalation(occurrence_count: int) -> None:
    """Announce when an error is being escalated due to frequency."""
    if occurrence_count >= 3:
        ui.show_adaptive(
            axis="error-patterns",
            message=(
                f"This error has recurred {occurrence_count} times — "
                f"escalating to a more aggressive fix strategy."
            ),
        )


# ── Axis 3: System Context ────────────────────────────────────


def announce_system_adaptations(
    system_context: dict[str, Any],
    module_name: str,
) -> None:
    """Announce adaptations based on detected system capabilities."""
    os_name = system_context.get("os", "")
    package_managers = system_context.get("package_managers", [])
    llm_provider = system_context.get("llm_provider")
    llm_tier = system_context.get("llm_tier", "template")

    # LLM tier adaptation
    if llm_tier == "local":
        ui.show_adaptive(
            axis="system",
            message=f"Using local LLM ({llm_provider}) — your prompts stay private.",
        )
    elif llm_tier == "cloud":
        ui.show_adaptive(
            axis="system",
            message="Using cloud LLM (Gemini) — prompts are sent to Google's API.",
        )
    else:
        ui.show_adaptive(
            axis="system",
            message="No LLM available — using template mode (no AI).",
        )

    # Platform-specific adaptations
    if "darwin" in os_name.lower():
        if "brew" in package_managers:
            ui.show_adaptive(
                axis="system",
                message="macOS with Homebrew detected — will use brew for system deps.",
            )
    elif "linux" in os_name.lower():
        if "apt" in package_managers:
            ui.show_adaptive(
                axis="system",
                message="Linux (apt) detected — will use apt for system deps.",
            )


def announce_module_detection(module_name: str, reason: str) -> None:
    """Announce which module was selected and why."""
    ui.show_adaptive(
        axis="system",
        message=f"Selected '{module_name}' module — {reason}.",
    )
