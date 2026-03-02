"""Onboarding flow — first-run setup.

Runs once on first ``shellock`` invocation.  Three phases:
    1. Automatic system detection (no questions)
    2. Module-driven preference questions
    3. LLM provider selection

Total time: ~30 seconds, 3-5 questions, one-time only.
"""

from __future__ import annotations

from typing import Any

from shellock_core.core import context, registry, ui
from shellock_core.core.module_loader import detect_modules, discover_modules, load_module
from shellock_core.core.schemas import LLMTier, UserProfile


def needs_onboarding() -> bool:
    """Check if onboarding has been completed."""
    profile = registry.load_profile()
    return not profile.onboarding_complete


def run_onboarding() -> UserProfile:
    """Run the full onboarding flow and return the populated profile."""
    ui.show_info("Welcome to Shellock.\n")

    # ── Phase 1: Automatic detection ────────────────────────────
    ui.show_info("Detecting system...")

    system_info = context.detect_system()

    ui.show_success(f"{system_info.os} · {system_info.arch} · {system_info.shell}")

    if system_info.package_managers:
        ui.show_success(f"Package managers: {', '.join(system_info.package_managers)}")

    if system_info.llm_provider:
        model_str = f" ({system_info.llm_model})" if system_info.llm_model else ""
        ui.show_success(f"Local LLM: {system_info.llm_provider}{model_str}")
    else:
        ui.show_warning("No local LLM detected")

    # Detect which modules are relevant
    # (check current directory, but also just list what's available)
    available = discover_modules()
    ui.show_success(f"Available modules: {', '.join(available)}")

    profile = UserProfile(system=system_info)

    # ── Phase 2: Module-driven questions ────────────────────────
    ui.show_info("")
    ui.show_info("Quick setup (you can change these anytime):")

    for mod_name in available:
        module = load_module(mod_name)
        if module is None:
            continue

        questions = module.onboarding_questions()
        for q in questions:
            answer = _ask_question(q)
            if answer:
                profile.record_choice(q["key"], answer)

    # ── Phase 3: LLM preference ────────────────────────────────
    config = registry.load_config()

    if system_info.llm_tier == LLMTier.LOCAL:
        ui.show_info("")
        model_str = f" with {system_info.llm_model}" if system_info.llm_model else ""
        ui.show_info(f"LLM: {system_info.llm_provider}{model_str} detected")

        from rich.console import Console
        r = Console().input(
            "  [dim]Use this model?[/] [dim]\\[yes / skip LLM][/] → "
        ).strip().lower()

        if r not in ("skip", "no", "n"):
            config.llm_provider = system_info.llm_provider or "ollama"
            if system_info.llm_model:
                config.llm_model = system_info.llm_model
    elif system_info.llm_tier == LLMTier.CLOUD:
        ui.show_info("")
        ui.show_info("No local LLM found. Options:")
        ui.show_info("  1. Install Ollama (recommended, private, offline)")
        ui.show_info("  2. Configure cloud LLM later: shellock config set llm.provider openai")
        ui.show_info("  3. Template-only mode (no AI)")
    else:
        ui.show_info("")
        ui.show_info("No LLM available. Running in template-only mode.")
        ui.show_info("Install Ollama later for the full experience.")

    # ── Save ────────────────────────────────────────────────────
    profile.onboarding_complete = True
    registry.save_profile(profile)
    registry.save_config(config)

    ui.show_info("")
    ui.show_success("Profile saved to ~/.shellock/profile.json")
    ui.show_success("Ready. Run: shellock init \"describe your project\"")

    return profile


def _ask_question(q: dict[str, Any]) -> str | None:
    """Ask a single onboarding question and return the answer."""
    options = q.get("options", [])
    default = q.get("default", "")

    if not options:
        return default

    options_str = " / ".join(
        f"[bold]{o}[/]" if o == default else o for o in options
    )

    try:
        from rich.console import Console
        answer = Console().input(
            f"  {q['question']} [{options_str}] → "
        ).strip().lower()
    except (ImportError, EOFError):
        answer = input(f"  {q['question']} [{'/'.join(options)}] → ").strip().lower()

    if not answer:
        return default

    # Match partial input
    for opt in options:
        if opt.lower().startswith(answer):
            return opt

    return answer if answer in options else default
