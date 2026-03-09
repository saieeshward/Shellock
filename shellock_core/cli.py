"""Shellock CLI — the main entry point.

Commands:
    shellock init "description"   — create a new environment
    shellock fix                  — diagnose and fix errors
    shellock list                 — show project history
    shellock rollback [action_id] — undo an action
    shellock modules              — list available modules
    shellock config               — manage configuration
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer

from shellock_core import __version__

app = typer.Typer(
    name="shellock",
    help="Adaptive Terminal Environment Orchestrator",
    no_args_is_help=True,
    add_completion=False,
)


def _check_onboarding() -> None:
    """Run onboarding if this is the first invocation."""
    from shellock_core.core.onboarding import needs_onboarding, run_onboarding

    if needs_onboarding():
        run_onboarding()


# ── init ────────────────────────────────────────────────────────


@app.command()
def init(
    description: str = typer.Argument(
        ..., help="Describe the environment you want, e.g. 'python 3.11 fastapi project'"
    ),
    module: Optional[str] = typer.Option(
        None, "--module", "-m", help="Force a specific module (auto-detected if omitted)"
    ),
    template: Optional[str] = typer.Option(
        None, "--template", "-t", help="Use a template instead of LLM (no AI needed)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without executing"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve without prompts"),
) -> None:
    """Create a new environment from a natural-language description."""
    from shellock_core.core import context, dispatcher, registry, ui
    from shellock_core.core.llm import LLMClient
    from shellock_core.core.module_loader import detect_modules, get_module
    from shellock_core.core.schemas import (
        ActionType,
        Command,
        EnvSpec,
        PackageSpec,
    )

    _check_onboarding()

    cwd = os.getcwd()
    profile = registry.load_profile()
    config = registry.load_config()

    # Detect or select module
    if module:
        active_module = get_module(module)
    else:
        detected = detect_modules(cwd)
        if not detected:
            # No project files found — try to infer from description
            ui.show_info("No project files detected. Inferring module from description...")
            # Default to python for now
            active_module = get_module("python")
        elif len(detected) == 1:
            active_module = detected[0]
            ui.show_info(f"Detected module: {active_module.name}")
        else:
            ui.show_info(f"Detected modules: {', '.join(m.name for m in detected)}")
            ui.show_info(f"Using first match: {detected[0].name}")
            active_module = detected[0]

    # Gather context
    sys_context = context.detect_system()
    proj_context = context.detect_project_context(cwd)
    introspection = active_module.introspect(cwd)

    full_context = {
        "system": sys_context.model_dump(),
        "project": proj_context,
        "introspection": introspection,
    }

    # Generate spec (LLM or template)
    if template:
        spec_dict = active_module.build_spec(template, full_context)
    else:
        llm = LLMClient(config, sys_context.llm_tier)
        if llm.is_available():
            ui.show_info("Generating environment spec...")
            spec_dict = llm.generate_spec(
                description=description,
                module_name=active_module.name,
                system_context=sys_context.model_dump(),
                user_preferences=profile.preferences,
                project_context=proj_context,
            )
            if spec_dict is None:
                ui.show_warning("LLM could not generate a valid spec. Falling back to module defaults.")
                spec_dict = active_module.build_spec(description, full_context)
        else:
            ui.show_warning("No LLM available. Using module defaults.")
            spec_dict = active_module.build_spec(description, full_context)

    # Build the EnvSpec
    try:
        # Ensure packages are PackageSpec objects
        if "packages" in spec_dict:
            spec_dict["packages"] = [
                p if isinstance(p, dict) else {"name": p}
                for p in spec_dict["packages"]
            ]
        spec = EnvSpec.model_validate(spec_dict)
    except Exception as e:
        ui.show_error(f"Invalid spec: {e}")
        raise typer.Exit(1)

    # Ensure env_path is set
    if not spec.env_path:
        from pathlib import Path

        spec.env_path = str(Path.home() / ".shellock" / "envs" / spec.env_id)

    # Validate spec against system reality
    warnings = active_module.validate_spec(spec.model_dump())

    # Show approval screen
    if yes:
        ui.show_spec_preview(spec, warnings)
        approved = True
    else:
        approved = ui.show_spec_approval(spec, warnings)
    if not approved:
        ui.show_info("Cancelled.")
        raise typer.Exit(0)

    spec.approved = True

    # Generate commands from module
    commands = active_module.dispatch(spec.model_dump())
    command_objects = [
        Command.model_validate(c) if isinstance(c, dict) else Command(command=str(c))
        for c in commands
    ]

    # Validate commands against allowlist
    validated = dispatcher.validate_commands(
        command_objects,
        active_module.allowed_commands,
        active_module.blocked_patterns,
    )

    # Show command approval
    if yes:
        approve_safe = True
        approve_caution = True
        ui.show_commands_preview(validated)
    else:
        approve_safe, approve_caution = ui.show_commands(validated)

    if not approve_safe:
        ui.show_info("Cancelled.")
        raise typer.Exit(0)

    # Filter commands based on approval
    to_run = []
    for cmd in validated:
        from shellock_core.core.schemas import Impact

        if cmd.impact == Impact.SAFE:
            to_run.append(cmd)
        elif cmd.impact == Impact.CAUTION and approve_caution:
            to_run.append(cmd)

    # Execute
    result = dispatcher.execute_commands(
        to_run,
        cwd=cwd,
        env_override=spec.env_vars or None,
        dry_run=dry_run,
    )

    # Record in audit trail
    registry.save_spec(cwd, spec)
    action_id = registry.record_action(
        project_path=cwd,
        action_type=ActionType.INIT,
        spec=spec.model_dump(mode="json"),
        commands_run=[r.command for r in result.results],
        result="success" if result.all_succeeded else "failed",
    )

    # Update user profile preferences
    for pkg in spec.packages:
        if pkg.name in active_module.suggestable_tools:
            profile.record_choice("tools", pkg.name)
    registry.save_profile(profile)

    if result.all_succeeded:
        ui.show_success(f"Environment '{spec.env_id}' created successfully")
        ui.show_info(f"Action logged: {action_id}")
    else:
        ui.show_error(f"Setup failed. Run 'shellock fix' to diagnose.")
        ui.show_info(f"Error: {result.failed_stderr[:200] if result.failed_stderr else 'unknown'}")


# ── fix ─────────────────────────────────────────────────────────


@app.command()
def fix(
    error_text: Optional[str] = typer.Argument(
        None, help="Paste the error message (or omit to read from last command)"
    ),
) -> None:
    """Diagnose and fix environment errors using the adaptive loop."""
    from shellock_core.core import context, dispatcher, registry, ui
    from shellock_core.core.llm import LLMClient
    from shellock_core.core.module_loader import get_module
    from shellock_core.core.schemas import (
        ActionType,
        Command,
        DiagnosisMethod,
        DiagnosisResult,
    )

    _check_onboarding()

    cwd = os.getcwd()
    config = registry.load_config()

    # Get the active spec to know which module to use
    spec = registry.load_spec(cwd)
    if spec is None:
        ui.show_error("No Shellock environment found in this directory.")
        ui.show_info("Run 'shellock init' first.")
        raise typer.Exit(1)

    active_module = get_module(spec.module)

    # If no error text provided, check last action
    if error_text is None:
        recent = registry.get_recent_actions(cwd, n=1)
        if recent and recent[0].get("result") == "failed":
            # Try to get stderr from the last failed action
            error_text = "Last action failed. Please paste the error output."
        else:
            ui.show_error("No error text provided. Paste the error or pipe it in.")
            ui.show_info("Usage: shellock fix \"error message here\"")
            raise typer.Exit(1)

    # Error fingerprinting
    fingerprint = registry.fingerprint_error(error_text)

    # Check for cascading errors (fix caused a new error)
    caused_by = registry.check_cascading_error(cwd, fingerprint)
    if caused_by:
        ui.show_warning(f"This may be caused by a recent fix ({caused_by})")

    # Check error frequency — escalate if recurring
    history = registry.load_history(cwd)
    freq = history.error_frequency.get(fingerprint, {})
    occurrence_count = freq.get("count", 0)

    if occurrence_count >= 3:
        ui.show_warning(f"This error has occurred {occurrence_count} times before.")
        if freq.get("fixes_that_worked"):
            ui.show_info(f"Previously successful fix: {freq['fixes_that_worked'][-1]}")

    # ── Resolution order ────────────────────────────────────────

    sys_context = context.detect_system()
    error_context = {
        "system": sys_context.model_dump(),
        "project": context.detect_project_context(cwd),
        "introspection": active_module.introspect(cwd),
        "recent_actions": registry.get_recent_actions(cwd),
        "caused_by": caused_by,
        "occurrence_count": occurrence_count,
    }

    diagnosis = None

    # Layer 1: System introspection (instant, accurate)
    ui.show_info("Diagnosing via system introspection...")
    introspection_result = active_module.diagnose(error_text, error_context)
    if introspection_result:
        diagnosis = DiagnosisResult(
            diagnosed=True,
            method=DiagnosisMethod.INTROSPECTION,
            fix=introspection_result,
            error_fingerprint=fingerprint,
        )

    # Layer 2: Built-in error patterns (fast, offline)
    if not diagnosis:
        ui.show_info("Checking known error patterns...")
        pattern_match = active_module.match_error_pattern(error_text)
        if pattern_match:
            diagnosis = DiagnosisResult(
                diagnosed=True,
                method=DiagnosisMethod.KNOWLEDGE_BASE,
                fix=pattern_match,
                error_fingerprint=fingerprint,
            )

    # Layer 3: LLM diagnosis (smart, slower)
    if not diagnosis:
        llm = LLMClient(config, sys_context.llm_tier)
        if llm.is_available():
            ui.show_info("Consulting LLM for diagnosis...")
            llm_result = llm.diagnose_error(
                stderr=error_text,
                system_context=sys_context.model_dump(),
                recent_actions=registry.get_recent_actions(cwd),
            )
            if llm_result and llm_result.get("diagnosed"):
                diagnosis = DiagnosisResult(
                    diagnosed=True,
                    method=DiagnosisMethod.LLM,
                    fix=llm_result.get("fix"),
                    error_fingerprint=fingerprint,
                )

    # Layer 4: "I don't know"
    if not diagnosis:
        diagnosis = DiagnosisResult(
            diagnosed=False,
            method=DiagnosisMethod.UNKNOWN,
            suggestions=[
                "Try rephrasing the error or providing more context",
                f"Search: https://stackoverflow.com/search?q={error_text[:50].replace(' ', '+')}",
            ],
            error_fingerprint=fingerprint,
        )

    # Show diagnosis and ask to apply
    should_apply = ui.show_diagnosis(diagnosis)

    if should_apply and diagnosis.fix:
        fix_commands = diagnosis.fix.get("commands", [])
        if fix_commands:
            command_objects = [Command(command=c, description="fix command") for c in fix_commands]
            validated = dispatcher.validate_commands(
                command_objects,
                active_module.allowed_commands,
                active_module.blocked_patterns,
            )

            result = dispatcher.execute_commands(validated, cwd=cwd)

            registry.record_action(
                project_path=cwd,
                action_type=ActionType.FIX,
                commands_run=[r.command for r in result.results],
                result="success" if result.all_succeeded else "failed",
                trigger_error=error_text[:200],
                error_fingerprint=fingerprint,
                fix_applied=diagnosis.fix,
                caused_by=caused_by,
                diagnosis_method=diagnosis.method,
            )

            if result.all_succeeded:
                ui.show_success("Fix applied successfully")
            else:
                ui.show_error("Fix failed. Check the output above.")
    elif not diagnosis.diagnosed:
        ui.show_info("No fix available.")


# ── list ────────────────────────────────────────────────────────


@app.command(name="list")
def list_history() -> None:
    """Show the project's action history."""
    from shellock_core.core import registry, ui

    cwd = os.getcwd()
    history = registry.load_history(cwd)

    if not history.actions:
        ui.show_info("No history found for this project.")
        ui.show_info("Run 'shellock init' to get started.")
        raise typer.Exit(0)

    actions = [a.model_dump(mode="json") for a in history.actions]
    ui.show_history(actions)


# ── rollback ────────────────────────────────────────────────────


@app.command()
def rollback(
    action_id: Optional[str] = typer.Argument(
        None, help="ID of the action to rollback (defaults to last action)"
    ),
) -> None:
    """Undo a previous action."""
    from shellock_core.core import registry, ui
    from shellock_core.core.schemas import ActionType

    cwd = os.getcwd()
    history = registry.load_history(cwd)

    if not history.actions:
        ui.show_error("No actions to rollback.")
        raise typer.Exit(1)

    # Find the action to rollback
    if action_id:
        target = next((a for a in history.actions if a.id == action_id), None)
        if not target:
            ui.show_error(f"Action '{action_id}' not found.")
            raise typer.Exit(1)
    else:
        target = history.actions[-1]

    ui.show_info(f"Rolling back action: {target.id} ({target.type.value})")
    ui.show_info(f"Commands that were run: {', '.join(target.commands_run[:5])}")

    # Record the rollback
    registry.record_action(
        project_path=cwd,
        action_type=ActionType.ROLLBACK,
        result="recorded",
        trigger_error=f"Rollback of {target.id}",
    )

    ui.show_success(f"Rollback of {target.id} recorded.")
    ui.show_info("Note: Automatic command reversal coming soon. For now, review the commands above.")


# ── modules ─────────────────────────────────────────────────────


@app.command()
def modules() -> None:
    """List available Shellock modules."""
    from shellock_core.core import ui
    from shellock_core.core.module_loader import discover_modules, load_module

    available = discover_modules()

    if not available:
        ui.show_info("No modules found.")
        raise typer.Exit(0)

    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Available Modules", border_style="dim")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Triggers", style="dim")

    for name in available:
        mod = load_module(name)
        if mod:
            table.add_row(
                mod.name,
                mod.description,
                ", ".join(mod.triggers[:3]),
            )
        else:
            table.add_row(name, "[dim]failed to load[/]", "")

    console.print(table)


# ── config ──────────────────────────────────────────────────────


@app.command()
def config(
    key: Optional[str] = typer.Argument(None, help="Config key to get/set (e.g. llm.provider)"),
    value: Optional[str] = typer.Argument(None, help="Value to set"),
) -> None:
    """View or modify Shellock configuration."""
    from shellock_core.core import registry, ui

    cfg = registry.load_config()

    if key is None:
        # Show all config
        ui.show_info("Current configuration:")
        for k, v in cfg.model_dump().items():
            if k == "llm_api_key" and v:
                v = v[:8] + "..."  # mask key
            ui.show_info(f"  {k}: {v}")
        return

    if value is None:
        # Get a specific key
        data = cfg.model_dump()
        if key in data:
            ui.show_info(f"{key}: {data[key]}")
        else:
            ui.show_error(f"Unknown config key: {key}")
        return

    # Set a key
    data = cfg.model_dump()
    if key in data:
        data[key] = value
        cfg = registry.load_config().__class__.model_validate(data)
        registry.save_config(cfg)
        ui.show_success(f"Set {key} = {value}")
    else:
        ui.show_error(f"Unknown config key: {key}")


# ── version ─────────────────────────────────────────────────────


@app.command()
def version() -> None:
    """Show Shellock version."""
    from shellock_core.core import ui
    ui.show_info(f"Shellock v{__version__}")


# ── Main ────────────────────────────────────────────────────────


def main() -> None:
    app()


if __name__ == "__main__":
    main()
