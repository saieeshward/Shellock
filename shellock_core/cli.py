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

import os
import re
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


def _sanitize_env_id(raw: str) -> str:
    """Sanitize an env ID: lowercase, replace spaces/special chars with hyphens, strip edges."""
    import re
    sanitized = raw.strip().lower()
    sanitized = re.sub(r"[^a-z0-9._-]", "-", sanitized)  # replace non-safe chars
    sanitized = re.sub(r"-{2,}", "-", sanitized)          # collapse multiple hyphens
    sanitized = sanitized.strip("-")                       # no leading/trailing hyphens
    return sanitized or "shellock-env"


def _activate_env(env_name: str, env_path: str) -> None:
    """Spawn a subshell with the given environment activated."""
    import subprocess
    from shellock_core.core import ui

    is_windows = os.name == "nt"
    bin_dir = Path(env_path) / ("Scripts" if is_windows else "bin")

    if not bin_dir.is_dir():
        ui.show_warning(f"Environment not ready (no {'Scripts' if is_windows else 'bin'}/ directory).")
        ui.show_info(f"Activate later with: shellock use {env_name}")
        return

    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(env_path)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env.pop("PYTHONHOME", None)
    env["SHELLOCK_ENV"] = env_name

    if is_windows:
        shell = os.environ.get("COMSPEC", "cmd.exe")
        shell_args = [shell]
    else:
        shell = os.environ.get("SHELL", "/bin/sh")
        shell_args = [shell, "-i"]

    ui.show_success(f"Entering '{env_name}' — type 'exit' to leave.")

    try:
        subprocess.run(shell_args, env=env)
    except KeyboardInterrupt:
        pass


def _check_conflicts(spec: "EnvSpec", module: "ShellockModule") -> str | None:
    """Run a quick conflict pre-detection before install."""
    import subprocess
    if module.name == "python" and spec.packages:
        pkg_names = [p.to_install_string() for p in spec.packages]
        try:
            result = subprocess.run(
                ["pip", "install", "--dry-run", "--report", "-", *pkg_names],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0 and "conflict" in result.stderr.lower():
                return result.stderr[:200]
        except Exception:
            pass
    return None


def _infer_module_from_description(description: str) -> "ShellockModule":
    """Infer the correct module from description keywords when no trigger files exist."""
    from shellock_core.core.module_loader import get_module

    desc_lower = description.lower()
    node_keywords = {"npm", "node", "next", "nextjs", "next.js", "react", "vue",
                     "angular", "svelte", "yarn", "pnpm", "express", "typescript"}
    if any(kw in desc_lower.split() or kw in desc_lower for kw in node_keywords):
        return get_module("node")
    return get_module("python")


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
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Explicitly name the environment (overrides auto-generated name)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without executing"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve without prompts"),
) -> None:
    """Create a new environment from a natural-language description."""
    from shellock_core.core import adaptive, context, dispatcher, registry, ui
    from shellock_core.core.llm import LLMClient
    from shellock_core.core.module_loader import detect_modules, get_module
    from shellock_core.core.schemas import (
        ActionType,
        Command,
        EnvSpec,
        LLMTier,
        PackageSpec,
    )

    _check_onboarding()

    cwd = os.getcwd()
    profile = registry.load_profile()
    config = registry.load_config()

    # Detect or select module
    if module:
        try:
            active_module = get_module(module)
        except Exception:
            ui.show_error(f"Module '{module}' not found. Run 'shellock modules' to see available modules.")
            raise typer.Exit(1)
        adaptive.announce_module_detection(active_module.name, f"forced via --module {module}")
    else:
        detected = detect_modules(cwd)
        if not detected:
            # No trigger files found — infer module from description text
            active_module = _infer_module_from_description(description)
            adaptive.announce_module_detection(active_module.name, "inferred from description text")
        elif len(detected) == 1:
            active_module = detected[0]
            adaptive.announce_module_detection(active_module.name, f"detected trigger files in {cwd}")
        else:
            active_module = detected[0]
            adaptive.announce_module_detection(active_module.name, f"first of {len(detected)} detected modules")
    ui.show_info(f"Module: {active_module.name}")

    # Gather context
    sys_context = context.detect_system()
    proj_context = context.detect_project_context(cwd)
    introspection = active_module.introspect(cwd)

    # Axis 3: System context announcements
    adaptive.announce_system_adaptations(sys_context.model_dump(), active_module.name)

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
            # Show which LLM tier we're using
            if sys_context.llm_tier == LLMTier.LOCAL and llm._check_ollama():
                ui.show_info(f"LLM: {config.llm_model} via Ollama (local)")
            elif config.llm_api_key:
                ui.show_info(f"LLM: Gemini 2.0 Flash via cloud (free tier)")
            else:
                tier_label = sys_context.llm_tier.value
                ui.show_info(f"LLM: {config.llm_model} via {tier_label}")
            spec_dict = llm.generate_spec(
                description=description,
                module_name=active_module.name,
                system_context=sys_context.model_dump(),
                user_preferences=profile.preferences,
                project_context=proj_context,
            )
            if spec_dict is None:
                ui.show_warning("LLM returned invalid spec — falling back to templates.")
                spec_dict = active_module.build_spec(description, full_context)
            elif not spec_dict.get("packages"):
                ui.show_warning(
                    "Shellock couldn't interpret that prompt. "
                    "Try being more specific, e.g. 'python FastAPI + postgres' or 'npm React + TypeScript'."
                )
                ui.show_info("Falling back to template mode...")
                spec_dict = active_module.build_spec(description, full_context)
        else:
            import shutil
            if shutil.which("ollama"):
                ui.show_warning("Ollama installed but not running. Start with: ollama serve")
            if config.llm_api_key:
                ui.show_info("Trying Gemini cloud fallback...")
            else:
                ui.show_info("No LLM available — using template mode.")
            spec_dict = active_module.build_spec(description, full_context)

    # Build the EnvSpec
    try:
        if name:
            spec_dict["env_id"] = _sanitize_env_id(name)
            spec_dict["env_path"] = str(Path.home() / ".shellock" / "envs" / spec_dict["env_id"])
        else:
            # Sanitize LLM-generated env_id too
            spec_dict["env_id"] = _sanitize_env_id(spec_dict.get("env_id", "shellock-env"))
            
        # Overwrite module with the strictly detected one to prevent LLM hallucinations
        spec_dict["module"] = active_module.name

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

    # Axis 1: Suggest tools from user preferences
    current_pkg_names = [p.name for p in spec.packages]
    suggested = adaptive.suggest_from_preferences(profile, "tools", current_pkg_names)
    for tool in suggested:
        spec.packages.append(PackageSpec(name=tool))

    # Ensure env_path is set
    if not spec.env_path:
        spec.env_path = str(Path.home() / ".shellock" / "envs" / spec.env_id)

    # Check if environment already exists
    if Path(spec.env_path).is_dir() and not dry_run:
        if yes:
            ui.show_warning(f"Environment '{spec.env_id}' already exists — will be overwritten.")
        else:
            ui.show_warning(f"Environment '{spec.env_id}' already exists.")
            ui.show_info("Use a different --name, or run 'shellock destroy' to remove it first.")
            raise typer.Exit(1)

    # Validate spec against system reality
    warnings = active_module.validate_spec(spec.model_dump())

    # Generate commands from module (needed for unified approval screen)
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

    # Single approval screen: spec + commands together (loop for edit/explain)
    if yes:
        ui.show_plan_preview(spec, validated, warnings)
        approved = True
    else:
        while True:
            result = ui.show_approval(spec, validated, warnings)
            if result is True:
                approved = True
                break
            elif result is False:
                approved = False
                break
            elif result == "edit":
                spec = ui.prompt_edit_spec(spec)
                # Re-validate and re-generate commands after editing
                warnings = active_module.validate_spec(spec.model_dump())
                commands = active_module.dispatch(spec.model_dump())
                command_objects = [
                    Command.model_validate(c) if isinstance(c, dict) else Command(command=str(c))
                    for c in commands
                ]
                validated = dispatcher.validate_commands(
                    command_objects,
                    active_module.allowed_commands,
                    active_module.blocked_patterns,
                )
                continue
            elif result == "explain":
                ui.show_explain(spec)
                continue
    if not approved:
        ui.show_info("Cancelled.")
        raise typer.Exit(0)

    spec.approved = True

    # Filter: run safe + caution (user already approved the full plan)
    from shellock_core.core.schemas import Impact

    to_run = [cmd for cmd in validated if cmd.impact != Impact.BLOCKED]

    # Conflict pre-detection dry run (pip check / npm ls)
    if not dry_run and spec.packages:
        conflicts = _check_conflicts(spec, active_module)
        if conflicts:
            ui.show_warning(f"Potential conflicts detected: {conflicts}")
            if not yes:
                ui.show_info("Proceeding anyway (conflicts may resolve during install).")

    # Execute
    result = dispatcher.execute_commands(
        to_run,
        cwd=cwd,
        env_override=spec.env_vars or None,
        dry_run=dry_run,
    )

    # Record in audit trail
    rollback_cmds = [cmd.rollback_command for cmd in reversed(to_run) if cmd.rollback_command]
    registry.save_spec(cwd, spec)
    registry.record_action(
        project_path=cwd,
        action_type=ActionType.INIT,
        spec=spec.model_dump(mode="json"),
        commands_run=[r.command for r in result.results],
        rollback_commands=rollback_cmds,
        result="success" if result.all_succeeded else "failed",
        failed_stderr=result.failed_stderr if not result.all_succeeded else None,
    )

    # Update user profile preferences
    for pkg in spec.packages:
        if pkg.name in active_module.suggestable_tools:
            profile.record_choice("tools", pkg.name)
    registry.save_profile(profile)

    if result.all_succeeded:
        ui.show_success(f"Environment '{spec.env_id}' created successfully!")

        # Post-install: lock file + security scan
        if not dry_run and spec.env_path:
            lock = registry.write_lock_file(spec.env_path, active_module.name)
            if lock:
                ui.show_info(f"Lock file: {lock}")

            scan = registry.run_security_scan(spec.env_path, active_module.name)
            if scan.get("scanned"):
                vulns = scan.get("vulnerabilities", [])
                if vulns:
                    ui.show_warning(f"Security scan ({scan['tool']}): {len(vulns)} issue(s) found")
                    for v in vulns[:3]:
                        if isinstance(v, dict):
                            ui.show_info(f"  - {v.get('name', v.get('issue', 'unknown'))}")
                else:
                    ui.show_success(f"Security scan ({scan['tool']}): no issues found")

        # Auto-activate: offer to drop into the environment
        if not dry_run and spec.env_path and not yes:
            if ui.prompt_activate(spec.env_id):
                _activate_env(spec.env_id, spec.env_path)
        elif not dry_run and spec.env_path:
            ui.show_info(f"Activate with: shellock use {spec.env_id}")
    else:
        ui.show_error("Setup failed. Run 'shellock fix' to diagnose.")
        if result.failed_stderr:
            ui.show_info(f"Error: {result.failed_stderr[:200]}")


# ── fix ─────────────────────────────────────────────────────────


@app.command()
def fix(
    error_text: Optional[str] = typer.Argument(
        None, help="Paste the error message (or omit to read from last command)"
    ),
) -> None:
    """Diagnose and fix environment errors using the adaptive loop."""
    from shellock_core.core import adaptive, context, dispatcher, registry, ui
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

    try:
        active_module = get_module(spec.module)
    except Exception:
        ui.show_error(f"Module '{spec.module}' not available.")
        raise typer.Exit(1)

    # If no error text provided, check last action for stored stderr
    if error_text is None:
        recent = registry.get_recent_actions(cwd, n=1)
        if recent and recent[0].get("result") == "failed":
            stored_stderr = recent[0].get("failed_stderr")
            if stored_stderr:
                error_text = stored_stderr
                ui.show_info(f"Using error from last failed action: {error_text[:100]}")
            else:
                ui.show_error("Last action failed but no error output was stored.")
                ui.show_info("Usage: shellock fix \"paste the error message here\"")
                raise typer.Exit(1)
        else:
            ui.show_error("No recent failure found. Provide the error text.")
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
        adaptive.announce_error_escalation(occurrence_count)
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
            tier_label = "Ollama (local)" if sys_context.llm_tier.value == "local" else sys_context.llm_tier.value
            ui.show_info(f"Consulting LLM ({config.llm_model} via {tier_label})...")
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
        else:
            import shutil
            if shutil.which("ollama"):
                ui.show_info("Ollama is installed but not running — skipping LLM diagnosis. Start with: ollama serve")

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
            # Snapshot before applying fix
            if spec.env_path:
                snap = registry.save_snapshot(spec.env_path, label="pre-fix")
                if snap:
                    ui.show_info(f"Snapshot saved: {snap.name}")

            command_objects = [Command(command=c, description="fix command") for c in fix_commands]
            validated = dispatcher.validate_commands(
                command_objects,
                active_module.allowed_commands,
                active_module.blocked_patterns,
            )

            result = dispatcher.execute_commands(validated, cwd=cwd)

            # Derive rollback commands: pip install X → pip uninstall -y X
            fix_rollback_cmds = []
            for cmd_str in fix_commands:
                m = re.match(r'^(.*?\bpip\d*(?:\.exe)?)\s+install\s+(.+)$', cmd_str.strip())
                if m:
                    pip_exe, pkgs = m.group(1), m.group(2)
                    fix_rollback_cmds.append(f"{pip_exe} uninstall -y {pkgs}")

            registry.record_action(
                project_path=cwd,
                action_type=ActionType.FIX,
                commands_run=[r.command for r in result.results],
                rollback_commands=fix_rollback_cmds,
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
                raise typer.Exit(1)
        else:
            ui.show_error("Fix was diagnosed but contained no commands to run.")
            raise typer.Exit(1)
    elif not diagnosis.diagnosed:
        # show_diagnosis already displayed the "couldn't diagnose" panel
        raise typer.Exit(1)
    else:
        ui.show_info("Fix not applied.")


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
    ui.show_info("Environments are typically located in ~/.shellock/envs/")


@app.command()
def profile() -> None:
    """Show what preferences and errors Shellock has recorded."""
    from shellock_core.core import registry, ui

    cwd = os.getcwd()
    profile = registry.load_profile()
    history = registry.load_history(cwd)
    spec = registry.load_spec(cwd)

    ui.show_profile(profile, history, spec)


# ── rollback ────────────────────────────────────────────────────


@app.command()
def rollback(
    action_id: Optional[str] = typer.Argument(
        None, help="ID of the action to rollback (defaults to last non-rollback action)"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Undo a previous action by executing its stored rollback commands."""
    from shellock_core.core import dispatcher, registry, ui
    from shellock_core.core.schemas import ActionType, EnvSpec

    _check_onboarding()

    cwd = os.getcwd()
    history = registry.load_history(cwd)

    if not history.actions:
        ui.show_error("No actions to rollback.")
        raise typer.Exit(1)

    # Find the target action (skip ROLLBACK entries when defaulting)
    if action_id:
        target = next((a for a in history.actions if a.id == action_id), None)
        if not target:
            ui.show_error(f"Action '{action_id}' not found.")
            raise typer.Exit(1)
    else:
        target = next(
            (a for a in reversed(history.actions) if a.type != ActionType.ROLLBACK),
            None,
        )
        if not target:
            ui.show_error("No eligible actions to rollback.")
            raise typer.Exit(1)

    # Guard: rollback_commands may be absent on old history entries
    if not target.rollback_commands:
        ui.show_error(
            f"Action '{target.id}' has no stored rollback commands.\n"
            "This action was recorded before rollback support was added, "
            "or the module emits no rollback commands for this action type."
        )
        ui.show_info("You can manually undo by running the appropriate commands.")
        raise typer.Exit(1)

    ui.show_info(f"Target action: {target.id} ({target.type.value}) @ {str(target.timestamp)[:16]}")

    # Confirmation gate (skipped with --yes)
    if not yes:
        confirmed = ui.show_rollback_plan(target.id, target.type.value, target.rollback_commands)
        if not confirmed:
            ui.show_info("Rollback cancelled.")
            raise typer.Exit(0)

    # Execute rollback commands (bypasses allowlist/blocked-pattern checks)
    ui.show_info("Executing rollback commands...")
    rollback_result = dispatcher.execute_rollback_commands(
        target.rollback_commands,
        cwd=cwd,
    )

    # Restore the previous spec: walk backwards to find the entry just before target
    previous_spec: "EnvSpec | None" = None
    found_target = False
    for action in reversed(history.actions):
        if found_target and action.spec is not None:
            try:
                previous_spec = EnvSpec.model_validate(action.spec)
            except Exception:
                pass
            break
        if action.id == target.id:
            found_target = True

    if rollback_result.all_succeeded:
        if previous_spec is not None:
            registry.save_spec(cwd, previous_spec)
            ui.show_info(f"Restored spec to state before '{target.id}'.")
        else:
            spec_file = Path(cwd) / ".shellock" / "spec.json"
            if spec_file.exists():
                spec_file.unlink()
            ui.show_info("No prior spec found; spec.json removed.")

    # Record this rollback in history
    outcome = "success" if rollback_result.all_succeeded else "partial"
    registry.record_action(
        project_path=cwd,
        action_type=ActionType.ROLLBACK,
        commands_run=[r.command for r in rollback_result.results],
        result=outcome,
        trigger_error=f"Rollback of {target.id}",
    )

    if rollback_result.all_succeeded:
        ui.show_success(f"Rollback of '{target.id}' completed successfully.")
    else:
        ui.show_warning(
            "Rollback completed with errors. Some commands failed — check output above."
        )
        if rollback_result.first_error:
            ui.show_info(f"First error: {rollback_result.first_error.stderr[:200]}")
        raise typer.Exit(1)


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


# ── envs ───────────────────────────────────────────────────────


@app.command()
def envs() -> None:
    """List all Shellock environments."""
    from shellock_core.core import ui

    envs_dir = Path.home() / ".shellock" / "envs"

    try:
        if not envs_dir.is_dir() or not any(envs_dir.iterdir()):
            ui.show_info("No environments found.")
            ui.show_info("Create one with: shellock init \"python 3.11 project with requests\"")
            raise typer.Exit(0)
    except PermissionError:
        ui.show_error(f"Permission denied reading {envs_dir}")
        raise typer.Exit(1)

    ui.show_envs(envs_dir)


# ── use ────────────────────────────────────────────────────────


@app.command()
def use(
    env_name: str = typer.Argument(..., help="Name of the environment to activate"),
) -> None:
    """Activate a Shellock environment (spawns a subshell)."""
    from shellock_core.core import ui

    envs_dir = Path.home() / ".shellock" / "envs"
    env_path = envs_dir / env_name

    if not env_path.is_dir():
        ui.show_error(f"Environment '{env_name}' not found.")
        if envs_dir.is_dir():
            available = [d.name for d in envs_dir.iterdir() if d.is_dir()]
            if available:
                ui.show_info(f"Available: {', '.join(available)}")
        raise typer.Exit(1)

    ui.show_env_details(env_path)
    _activate_env(env_name, str(env_path))


# ── destroy ─────────────────────────────────────────────────────


@app.command()
def destroy(
    env_name: str = typer.Argument(..., help="Name of the environment to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Remove a Shellock environment permanently."""
    import shutil as _shutil
    from shellock_core.core import ui

    envs_dir = Path.home() / ".shellock" / "envs"
    env_path = envs_dir / env_name

    if not env_path.is_dir():
        ui.show_error(f"Environment '{env_name}' not found.")
        raise typer.Exit(1)

    if not force:
        from rich.console import Console
        console = Console()
        r = console.input(
            f"  [red]Permanently delete '{env_name}'?[/] [dim]\\[yes/no][/] → "
        ).strip().lower()
        if r not in ("yes", "y"):
            ui.show_info("Cancelled.")
            raise typer.Exit(0)

    _shutil.rmtree(env_path)
    ui.show_success(f"Environment '{env_name}' removed.")


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


# ── info ───────────────────────────────────────────────────────


@app.command()
def info(
    env_name: Optional[str] = typer.Argument(None, help="Environment name (defaults to current project's env)"),
) -> None:
    """Show detailed info about an environment."""
    from shellock_core.core import registry, ui

    if env_name:
        env_path = Path.home() / ".shellock" / "envs" / env_name
    else:
        cwd = os.getcwd()
        spec = registry.load_spec(cwd)
        if spec and spec.env_path:
            env_path = Path(spec.env_path)
            env_name = spec.env_id
        else:
            ui.show_error("No environment found. Provide a name or run from a Shellock project.")
            raise typer.Exit(1)

    if not env_path.is_dir():
        ui.show_error(f"Environment '{env_name}' not found at {env_path}")
        raise typer.Exit(1)

    ui.show_env_details(env_path)

    # Show lock file info if present
    lock_file = env_path / "shellock.lock"
    if lock_file.exists():
        import json as _json
        lock_data = _json.loads(lock_file.read_text())
        pkgs = lock_data.get("packages", {})
        ui.show_info(f"Locked packages: {len(pkgs)}")
        for name, ver in list(pkgs.items())[:10]:
            ui.show_info(f"  {name}=={ver}")
        if len(pkgs) > 10:
            ui.show_info(f"  ... and {len(pkgs) - 10} more")


# ── export ─────────────────────────────────────────────────────


@app.command(name="export")
def export_env(
    env_name: Optional[str] = typer.Argument(None, help="Environment name"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path"),
) -> None:
    """Export an environment spec to a portable JSON file."""
    import json as _json
    from shellock_core.core import registry, ui

    cwd = os.getcwd()
    spec = registry.load_spec(cwd)
    if spec is None:
        ui.show_error("No Shellock environment found in this directory.")
        raise typer.Exit(1)

    export_data = spec.model_dump(mode="json")
    export_data.pop("approved", None)
    export_data.pop("created_at", None)

    out_path = output or f"shellock-{spec.env_id}.json"
    Path(out_path).write_text(_json.dumps(export_data, indent=2) + "\n")
    ui.show_success(f"Exported to {out_path}")


# ── import ─────────────────────────────────────────────────────


@app.command(name="import")
def import_env(
    file_path: str = typer.Argument(..., help="Path to exported shellock JSON file"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Override environment name"),
) -> None:
    """Import an environment from an exported JSON file."""
    import json as _json
    from shellock_core.core import registry, ui
    from shellock_core.core.schemas import EnvSpec

    path = Path(file_path)
    if not path.exists():
        ui.show_error(f"File not found: {file_path}")
        raise typer.Exit(1)

    try:
        data = _json.loads(path.read_text())
        if name:
            data["env_id"] = _sanitize_env_id(name)
        spec = EnvSpec.model_validate(data)
    except Exception as e:
        ui.show_error(f"Invalid spec file: {e}")
        raise typer.Exit(1)

    ui.show_info(f"Importing environment: {spec.env_id} ({spec.module})")
    if spec.packages:
        ui.show_info(f"Packages: {', '.join(p.name for p in spec.packages)}")

    # Delegate to init with the spec's data
    init(
        description=spec.reasoning or f"Imported {spec.env_id}",
        module=spec.module,
        name=spec.env_id,
        template=None,
        dry_run=False,
        yes=False,
    )


# ── scan ───────────────────────────────────────────────────────


@app.command()
def scan(
    env_name: Optional[str] = typer.Argument(None, help="Environment name"),
) -> None:
    """Run a security scan on an environment."""
    from shellock_core.core import registry, ui

    if env_name:
        env_path = str(Path.home() / ".shellock" / "envs" / env_name)
        module_name = "python"  # default guess
    else:
        cwd = os.getcwd()
        spec = registry.load_spec(cwd)
        if spec and spec.env_path:
            env_path = spec.env_path
            module_name = spec.module
        else:
            ui.show_error("No environment found. Provide a name or run from a Shellock project.")
            raise typer.Exit(1)

    ui.show_info(f"Scanning {env_path}...")
    results = registry.run_security_scan(env_path, module_name)

    if not results.get("scanned"):
        ui.show_warning("Could not run security scan. Install pip-audit or ensure npm is available.")
        return

    vulns = results.get("vulnerabilities", [])
    if vulns:
        ui.show_warning(f"Found {len(vulns)} issue(s) via {results['tool']}:")
        for v in vulns:
            if isinstance(v, dict):
                name = v.get("name", v.get("issue", "unknown"))
                sev = v.get("severity", "")
                ui.show_info(f"  - {name}" + (f" ({sev})" if sev else ""))
    else:
        ui.show_success(f"No vulnerabilities found ({results['tool']})")


# ── adopt ──────────────────────────────────────────────────────


@app.command()
def adopt(
    env_path: str = typer.Argument(..., help="Path to existing virtual environment"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Name for the adopted environment"),
) -> None:
    """Adopt an existing virtual environment into Shellock management."""
    from shellock_core.core import registry, ui
    from shellock_core.core.schemas import EnvSpec

    path = Path(env_path).resolve()
    if not path.is_dir():
        ui.show_error(f"Directory not found: {env_path}")
        raise typer.Exit(1)

    # Verify it's a venv
    has_pyvenv = (path / "pyvenv.cfg").exists()
    has_node = (path / "package.json").exists()

    if not has_pyvenv and not has_node:
        ui.show_error("This doesn't look like a Python venv or Node project.")
        raise typer.Exit(1)

    env_name = name or _sanitize_env_id(path.name)
    module_name = "python" if has_pyvenv else "node"

    # Symlink or copy into shellock envs
    target = Path.home() / ".shellock" / "envs" / env_name
    if target.exists():
        ui.show_error(f"Environment '{env_name}' already exists.")
        raise typer.Exit(1)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(path)

    # Create spec
    spec = EnvSpec(
        env_id=env_name,
        module=module_name,
        env_path=str(path),
        reasoning=f"Adopted from {env_path}",
        approved=True,
    )
    registry.save_spec(os.getcwd(), spec)
    ui.show_success(f"Adopted '{env_name}' ({module_name}) → {path}")


# ── generate ───────────────────────────────────────────────────

generate_app = typer.Typer(help="Generate Dockerfile or CI config from environment")
app.add_typer(generate_app, name="generate")


@generate_app.command()
def dockerfile(
    env_name: Optional[str] = typer.Argument(None, help="Environment name"),
    output: str = typer.Option("Dockerfile", "--output", "-o", help="Output file"),
) -> None:
    """Generate a Dockerfile from the current environment."""
    from shellock_core.core import registry, ui

    cwd = os.getcwd()
    spec = registry.load_spec(cwd)
    if spec is None:
        ui.show_error("No Shellock environment found. Run 'shellock init' first.")
        raise typer.Exit(1)

    lines = []
    if spec.module == "python":
        py_ver = spec.runtime_version or "3.11"
        lines.append(f"FROM python:{py_ver}-slim")
        lines.append("WORKDIR /app")
        lines.append("COPY . .")
        if spec.packages:
            pkgs = " ".join(p.to_install_string() for p in spec.packages)
            lines.append(f"RUN pip install --no-cache-dir {pkgs}")
        for key, val in spec.env_vars.items():
            lines.append(f"ENV {key}={val}")
        lines.append('CMD ["python", "app.py"]')
    elif spec.module == "node":
        lines.append("FROM node:lts-slim")
        lines.append("WORKDIR /app")
        lines.append("COPY package*.json ./")
        lines.append("RUN npm ci")
        lines.append("COPY . .")
        for key, val in spec.env_vars.items():
            lines.append(f"ENV {key}={val}")
        lines.append('CMD ["node", "index.js"]')
    else:
        ui.show_error(f"Dockerfile generation not supported for module '{spec.module}'")
        raise typer.Exit(1)

    content = "\n".join(lines) + "\n"
    Path(output).write_text(content)
    ui.show_success(f"Generated {output}")
    for line in lines:
        ui.show_info(f"  {line}")


@generate_app.command()
def ci(
    provider: str = typer.Option("github", "--provider", "-p", help="CI provider: github, gitlab"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path"),
) -> None:
    """Generate a CI configuration file."""
    from shellock_core.core import registry, ui

    cwd = os.getcwd()
    spec = registry.load_spec(cwd)
    if spec is None:
        ui.show_error("No Shellock environment found. Run 'shellock init' first.")
        raise typer.Exit(1)

    if provider == "github":
        out_path = output or ".github/workflows/ci.yml"
        content = _generate_github_ci(spec)
    elif provider == "gitlab":
        out_path = output or ".gitlab-ci.yml"
        content = _generate_gitlab_ci(spec)
    else:
        ui.show_error(f"Unknown CI provider: {provider}. Use 'github' or 'gitlab'.")
        raise typer.Exit(1)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(content)
    ui.show_success(f"Generated {out_path}")


def _generate_github_ci(spec: "EnvSpec") -> str:
    """Generate a GitHub Actions CI workflow."""
    if spec.module == "python":
        py_ver = spec.runtime_version or "3.11"
        pkgs = " ".join(p.to_install_string() for p in spec.packages) if spec.packages else ""
        return f"""name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '{py_ver}'
      - run: pip install {pkgs}
      - run: python -m pytest
"""
    elif spec.module == "node":
        return """name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 'lts/*'
      - run: npm ci
      - run: npm test
"""
    return "# Unsupported module\n"


def _generate_gitlab_ci(spec: "EnvSpec") -> str:
    """Generate a GitLab CI config."""
    if spec.module == "python":
        py_ver = spec.runtime_version or "3.11"
        pkgs = " ".join(p.to_install_string() for p in spec.packages) if spec.packages else ""
        return f"""image: python:{py_ver}

test:
  script:
    - pip install {pkgs}
    - python -m pytest
"""
    elif spec.module == "node":
        return """image: node:lts

test:
  script:
    - npm ci
    - npm test
"""
    return "# Unsupported module\n"


# ── setup (alias for init) ──────────────────────────────────────


@app.command()
def setup(
    description: str = typer.Argument(
        ..., help="Describe the environment you want, e.g. 'npm Next.js + Tailwind'"
    ),
    module: Optional[str] = typer.Option(
        None, "--module", "-m", help="Force a specific module (auto-detected if omitted)"
    ),
    template: Optional[str] = typer.Option(
        None, "--template", "-t", help="Use a template instead of LLM (no AI needed)"
    ),
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Explicitly name the environment"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without executing"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve without prompts"),
) -> None:
    """Create a new environment (alias for 'init')."""
    init(description=description, module=module, template=template, name=name, dry_run=dry_run, yes=yes)


# ── Main ────────────────────────────────────────────────────────


def main() -> None:
    app()


if __name__ == "__main__":
    main()
