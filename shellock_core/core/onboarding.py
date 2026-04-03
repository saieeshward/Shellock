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

        try:
            from rich.console import Console
            r = Console().input(
                "  [dim]Use this model?[/] [dim]\\[yes / skip LLM][/] → "
            ).strip().lower()
        except (ImportError, EOFError):
            r = input("  Use this model? [yes / skip LLM] → ").strip().lower()

        if r not in ("skip", "no", "n"):
            config.llm_provider = system_info.llm_provider or "ollama"
            if system_info.llm_model:
                config.llm_model = system_info.llm_model
    elif system_info.llm_tier == LLMTier.CLOUD:
        ui.show_info("")
        ui.show_info("No local LLM found, but internet is available.")
        ui.show_info("Shellock can use Gemini 2.0 Flash (free) as a cloud fallback.")
        config = _prompt_gemini_key(config)
    else:
        ui.show_info("")
        ui.show_info("No LLM available. Running in template-only mode.")
        ui.show_info("Install Ollama later for the full experience.")

    # Also offer Gemini key if local LLM was found (as a fallback)
    if system_info.llm_tier == LLMTier.LOCAL and not config.llm_api_key:
        ui.show_info("")
        ui.show_info("Optional: Add a Gemini API key for cloud fallback when Ollama is offline.")
        config = _prompt_gemini_key(config)

    # ── Phase 4: Shell activation function ────────────────────
    _offer_shell_activation(system_info.shell)

    # ── Save ────────────────────────────────────────────────────
    profile.onboarding_complete = True
    registry.save_profile(profile)
    registry.save_config(config)

    ui.show_info("")
    ui.show_success("Profile saved to ~/.shellock/profile.json")
    ui.show_success("Ready. Run: shellock setup \"describe your project\"")

    return profile


SHELL_ACTIVATION_SNIPPET = '''
# Shellock shell integration
shellock_activate() {
    local env_name="${1:-}"
    if [ -z "$env_name" ]; then
        echo "Usage: shellock_activate <env-name>"
        return 1
    fi
    local env_path="$HOME/.shellock/envs/$env_name"
    if [ ! -d "$env_path" ]; then
        echo "Environment '$env_name' not found."
        return 1
    fi
    export VIRTUAL_ENV="$env_path"
    export PATH="$env_path/bin:$PATH"
    unset PYTHONHOME
    export SHELLOCK_ENV="$env_name"
    echo "Activated '$env_name'"
}

shellock_deactivate() {
    if [ -n "$SHELLOCK_ENV" ]; then
        # Remove env bin from PATH
        PATH=$(echo "$PATH" | sed "s|$HOME/.shellock/envs/$SHELLOCK_ENV/bin:||")
        unset VIRTUAL_ENV SHELLOCK_ENV
        echo "Deactivated"
    fi
}
'''


def _offer_shell_activation(shell: str) -> None:
    """Offer to install shell activation functions."""
    from pathlib import Path

    ui.show_info("")
    ui.show_info("Shellock can add shell functions (shellock_activate / shellock_deactivate)")
    ui.show_info("to your shell config for quick environment switching.")

    rc_file = None
    if "zsh" in shell:
        rc_file = Path.home() / ".zshrc"
    elif "bash" in shell:
        rc_file = Path.home() / ".bashrc"

    if rc_file is None:
        ui.show_info(f"Unknown shell ({shell}) — skipping shell integration.")
        return

    try:
        from rich.console import Console
        r = Console().input(
            f"  [dim]Add to {rc_file.name}?[/] [dim]\\[yes/no][/] → "
        ).strip().lower()
    except (ImportError, EOFError):
        r = input(f"  Add to {rc_file.name}? [yes/no] → ").strip().lower()

    if r in ("yes", "y"):
        # Check if already installed
        existing = rc_file.read_text() if rc_file.exists() else ""
        if "shellock_activate" in existing:
            ui.show_info("Shell functions already installed.")
            return

        with open(rc_file, "a") as f:
            f.write(SHELL_ACTIVATION_SNIPPET)
        ui.show_success(f"Added to {rc_file.name}. Restart your shell or run: source {rc_file}")
    else:
        ui.show_info("Skipped. You can add them manually later.")


def _prompt_gemini_key(config: "ShelllockConfig") -> "ShelllockConfig":
    """Prompt the user for a Gemini API key."""
    from shellock_core.core.schemas import ShelllockConfig as _Cfg
    try:
        from rich.console import Console
        key = Console().input(
            "  [dim]Gemini API key (get free at https://aistudio.google.com/apikey)[/]\n"
            "  [dim]Paste key or press Enter to skip:[/] → "
        ).strip()
    except (ImportError, EOFError):
        key = input("  Gemini API key (Enter to skip): ").strip()

    if key:
        config.llm_api_key = key
        config.llm_provider = "gemini"
        config.llm_model = "gemini/gemini-2.0-flash"
        ui.show_success("Gemini API key saved.")
    else:
        ui.show_info("Skipped. You can add it later: shellock config llm_api_key YOUR_KEY")
    return config


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
