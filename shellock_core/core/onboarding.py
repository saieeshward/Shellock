"""Onboarding flow — first-run setup.

Runs once on first ``shellock`` invocation.  Four phases:
    1. Automatic system detection (no questions)
    2. Module-driven preference questions
    3. Local LLM setup (Ollama)
    4. Cloud LLM setup (Gemini / OpenAI / Anthropic / Other)

Total time: ~30 seconds, one-time only.
"""

from __future__ import annotations

import shutil
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

    # ── Phase 3: Local LLM setup ────────────────────────────────
    config = registry.load_config()
    ui.show_info("")
    ui.show_info("── LLM Setup ─────────────────────────────────────────")
    config = _setup_local_llm(system_info, config)

    # ── Phase 4: Cloud LLM setup ────────────────────────────────
    config = _setup_cloud_llm(config)

    # ── Phase 5: Shell activation function ────────────────────
    _offer_shell_activation(system_info.shell)

    # ── Save ────────────────────────────────────────────────────
    profile.onboarding_complete = True
    registry.save_profile(profile)
    registry.save_config(config)

    ui.show_info("")
    ui.show_success("Profile saved to ~/.shellock/profile.json")
    ui.show_success("Ready. Run: shellock init \"describe your project\"")

    return profile


# ── LLM setup helpers ───────────────────────────────────────────


def _prompt(label: str) -> str:
    """Single-line prompt with Rich fallback. Returns lowercased input."""
    try:
        from rich.console import Console
        return Console().input(f"  [dim]{label}[/] → ").strip().lower()
    except (ImportError, EOFError):
        return input(f"  {label} → ").strip().lower()


def _prompt_raw(label: str) -> str:
    """Like _prompt but preserves original casing (for keys and model names)."""
    try:
        from rich.console import Console
        return Console().input(f"  [dim]{label}[/] → ").strip()
    except (ImportError, EOFError):
        return input(f"  {label} → ").strip()


def _setup_local_llm(system_info: Any, config: Any) -> Any:
    """Step 1: Offer Ollama setup."""
    ui.show_info("")
    ui.show_info("Step 1/2 — Local LLM (private, offline, no API key needed)")

    if system_info.llm_tier == LLMTier.LOCAL:
        # Already running
        model_str = f" ({system_info.llm_model})" if system_info.llm_model else ""
        ui.show_success(f"Detected: {system_info.llm_provider}{model_str}")
        r = _prompt("Use this for Shellock? [yes/skip]")
        if r not in ("skip", "no", "n"):
            config.llm_provider = system_info.llm_provider or "ollama"
            if system_info.llm_model:
                config.llm_model = system_info.llm_model
            ui.show_success("Local LLM configured.")
        return config

    # Ollama installed but not running?
    if shutil.which("ollama"):
        ui.show_warning("Ollama is installed but not running.")
        ui.show_info("  Start it with: ollama serve")
        r = _prompt("Press Enter once running, or type 'skip'")
        if r != "skip":
            from shellock_core.core import context as _ctx
            new_sys = _ctx.detect_system()
            if new_sys.llm_tier == LLMTier.LOCAL:
                config.llm_provider = new_sys.llm_provider or "ollama"
                if new_sys.llm_model:
                    config.llm_model = new_sys.llm_model
                ui.show_success("Ollama connected.")
            else:
                ui.show_warning("Ollama not detected yet.")
                ui.show_info("  Configure later: shellock config llm_provider ollama")
        return config

    # Not installed
    ui.show_info("Ollama is not installed.")
    r = _prompt("Install Ollama for private, offline AI? [yes/skip]")
    if r in ("yes", "y"):
        _show_ollama_install_steps(system_info.os)
    else:
        ui.show_info("  Skipped. Install later from https://ollama.com")

    return config


def _show_ollama_install_steps(os_name: str) -> None:
    """Print OS-specific Ollama install instructions."""
    ui.show_info("")
    ui.show_info("  Ollama install steps:")
    if "windows" in os_name.lower():
        ui.show_info("    1. Download: https://ollama.com/download/OllamaSetup.exe")
        ui.show_info("    2. Run the installer, then open a new terminal")
        ui.show_info("    3. ollama pull llama3.2:3b")
    elif "darwin" in os_name.lower():
        ui.show_info("    1. brew install ollama")
        ui.show_info("    2. ollama serve          ← run in a separate terminal")
        ui.show_info("    3. ollama pull llama3.2:3b")
    else:
        ui.show_info("    1. curl -fsSL https://ollama.com/install.sh | sh")
        ui.show_info("    2. ollama serve          ← run in a separate terminal")
        ui.show_info("    3. ollama pull llama3.2:3b")
    ui.show_info("")
    ui.show_info("  After setup: shellock config llm_provider ollama")


def _setup_cloud_llm(config: Any) -> Any:
    """Step 2: Offer cloud LLM configuration with provider choice."""
    ui.show_info("")
    ui.show_info("Step 2/2 — Cloud LLM (used as fallback or primary)")

    r = _prompt("Configure a cloud LLM? [yes/skip]")
    if r not in ("yes", "y"):
        ui.show_info("  Skipped. Add later: shellock config llm_api_key YOUR_KEY")
        return config

    # Provider menu
    ui.show_info("")
    ui.show_info("  Choose a provider:")
    ui.show_info("    1. Gemini   — free tier  (aistudio.google.com/apikey)")
    ui.show_info("    2. OpenAI   — GPT models  (platform.openai.com/api-keys)")
    ui.show_info("    3. Anthropic — Claude models  (console.anthropic.com/settings/keys)")
    ui.show_info("    4. Other    — any litellm-compatible provider")

    choice = _prompt("Choose [1/2/3/4]")

    providers = {
        "1": ("gemini",    "gemini/gemini-2.5-flash",  "https://aistudio.google.com/apikey"),
        "2": ("openai",    "gpt-4o-mini",               "https://platform.openai.com/api-keys"),
        "3": ("anthropic", "anthropic/claude-haiku-4-5-20251001", "https://console.anthropic.com/settings/keys"),
    }

    if choice in providers:
        provider, suggested_model, key_url = providers[choice]
        ui.show_info(f"  Get your API key at: {key_url}")
    elif choice == "4":
        provider = _prompt_raw("Provider name (e.g. 'openai', 'groq')")
        suggested_model = ""
        key_url = ""
    else:
        ui.show_info("  Invalid choice — skipping cloud LLM setup.")
        return config

    # API key
    key = _prompt_raw("Paste API key (Enter to skip)")
    if not key:
        ui.show_info("  Skipped.")
        return config

    # Model name — suggest but let user override (this is the critical fix)
    if suggested_model:
        model = _prompt_raw(f"Model name (Enter for '{suggested_model}', or type your own)")
        model = model or suggested_model
    else:
        model = _prompt_raw("Model name (e.g. 'gemini/gemini-2.5-flash')")

    if not model:
        ui.show_warning("No model name provided — skipping cloud LLM.")
        return config

    config.llm_api_key = key
    config.llm_provider = provider
    config.llm_model = model
    ui.show_success(f"Cloud LLM configured: {model} via {provider}")
    return config


# ── Shell integration ───────────────────────────────────────────


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
        existing = rc_file.read_text() if rc_file.exists() else ""
        if "shellock_activate" in existing:
            ui.show_info("Shell functions already installed.")
            return

        with open(rc_file, "a") as f:
            f.write(SHELL_ACTIVATION_SNIPPET)
        ui.show_success(f"Added to {rc_file.name}. Restart your shell or run: source {rc_file}")
    else:
        ui.show_info("Skipped. You can add them manually later.")


# ── Question helpers ─────────────────────────────────────────────


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

    for opt in options:
        if opt.lower().startswith(answer):
            return opt

    return answer if answer in options else default
