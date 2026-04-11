"""UI layer — Rich terminal rendering.

All terminal output goes through this module.  Modules never print
directly — they return data, the UI renders it.  This makes it
trivial to swap Rich for plain output (SHELLOCK_PLAIN=1).

Key screens:
    - Environment spec approval (diff-style preview)
    - Command impact classification
    - Error diagnosis display
    - Audit trail listing
    - Onboarding wizard
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from shellock_core.core.schemas import Command, DiagnosisResult, EnvSpec, Impact, ProjectHistory, UserProfile


def _plain_mode() -> bool:
    """Check if Rich formatting is disabled."""
    return os.environ.get("SHELLOCK_PLAIN", "").strip() in ("1", "true", "yes")


def _shorten(text: str, width: int = 70) -> str:
    width = max(width, 4)
    if len(text) <= width:
        return text
    return text[: width - 3].rstrip() + "..."


def _format_tool_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{tool} ({count})" for tool, count in items)

def _collect_error_entries(history: ProjectHistory) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for fingerprint, data in history.error_frequency.items():
        entries.append({
            "fingerprint": fingerprint,
            "pattern": data.get("pattern", ""),
            "count": data.get("count", 0),
            "fixes_attempted": data.get("fixes_attempted") or [],
            "fixes_that_worked": data.get("fixes_that_worked") or [],
        })
    entries.sort(key=lambda item: item["count"], reverse=True)
    return entries

def _plain_profile(
    profile: UserProfile,
    history: ProjectHistory,
    profile_path: Path,
    spec: EnvSpec | None = None,
) -> None:
    print()
    print("--- Shellock profile ---")
    sys_info = profile.system
    os_line = f"{sys_info.os or 'unknown OS'} / {sys_info.arch or 'unknown arch'} / {sys_info.shell or 'unknown shell'}"
    print(f"System: {os_line}")
    pkg_managers = ", ".join(sys_info.package_managers) if sys_info.package_managers else "none detected"
    print(f"Package managers: {pkg_managers}")
    llm_provider = sys_info.llm_provider or "not configured"
    if sys_info.llm_model:
        llm_provider = f"{llm_provider} ({sys_info.llm_model})"
    print(f"LLM provider: {llm_provider}")
    print(f"Suggestion threshold: {profile.suggestion_threshold} uses")
    if profile.preferences:
        print("Preferences tracked:")
        for category in sorted(profile.preferences):
            print(f"  {category}: {_format_tool_counts(profile.preferences[category])}")
    else:
        print("Preferences tracked: none yet")
    if profile.rejected_suggestions:
        print(f"Rejected suggestions: {', '.join(profile.rejected_suggestions)}")
    else:
        print("Rejected suggestions: none")
    print(f"Profile file: {profile_path}")
    cpu_description = sys_info.cpu_info or "unknown CPU"
    logical = sys_info.cpu_logical_cores or "unknown"
    physical = sys_info.cpu_physical_cores or "unknown"
    print(f"CPU: {cpu_description} ({logical} logical / {physical} physical)")
    accel_tags = []
    if sys_info.gpu_info:
        accel_tags.append(sys_info.gpu_info)
    if sys_info.cuda_available:
        accel_tags.append("CUDA available")
    if sys_info.mps_available:
        accel_tags.append("MPS available")
    if accel_tags:
        print(f"Accelerators: {', '.join(accel_tags)}")
    else:
        print("Accelerators: CPU-only")
    entries = _collect_error_entries(history)
    if entries:
        print(f"Errors seen in this project ({len(entries)} tracked):")
        for entry in entries[:5]:
            print(f"  {entry['fingerprint']} - seen {entry['count']} times")
            print(f"     pattern: {_shorten(entry['pattern'], 80)}")
            attempts = len(entry['fixes_attempted'])
            successes = len(entry['fixes_that_worked'])
            if attempts or successes:
                print(f"     fixes attempted: {attempts}, succeeded: {successes}")
        if len(entries) > 5:
            print(f"  ...and {len(entries) - 5} more fingerprints")
    else:
        print("Errors seen in this project: none yet")
    print()
    if spec:
        print(f"Active spec: {spec.env_id} ({spec.module})")
        if spec.runtime_version:
            print(f"  Runtime: {spec.runtime_version}")
        if spec.packages:
            pkg_names = ", ".join(p.to_install_string() for p in spec.packages[:8])
            more = len(spec.packages) - 8
            if more > 0:
                pkg_names += f" +{more} more"
            print(f"  Packages: {pkg_names}")
        if spec.env_path:
            print(f"  Path: {spec.env_path}")

def show_approval(
    spec: EnvSpec,
    commands: list[Command],
    warnings: list[dict[str, Any]] | None = None,
) -> bool | str:
    """Display the environment spec AND commands in a single approval screen.

    Returns True if the user approves, False if rejected,
    or "edit" / "explain" for those actions.
    """
    if _plain_mode():
        return _plain_approval(spec, commands, warnings)

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    console.print()
    console.print(
        Panel(
            f"[bold cyan]Environment Plan[/] — [dim]{spec.module}[/]",
            border_style="cyan",
            padding=(0, 2),
        )
    )

    # Spec table
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column("Key", style="dim", width=16)
    table.add_column("Value")
    table.add_row("Name", f"[bold]{spec.env_id}[/]")
    if spec.runtime_version:
        table.add_row("Runtime", f"Python {spec.runtime_version}")
    if spec.packages:
        pkg_strs = [p.to_install_string() for p in spec.packages]
        table.add_row("Packages", ", ".join(pkg_strs))
    if spec.env_path:
        table.add_row("Path", f"[dim]{spec.env_path}[/]")
    if spec.env_vars:
        vars_str = ", ".join(f"{k}={v}" for k, v in spec.env_vars.items())
        table.add_row("Env vars", vars_str)
    console.print(table)

    # Warnings
    if warnings:
        console.print()
        for w in warnings:
            level = w.get("level", "info")
            msg = w.get("message", "")
            if level == "caution":
                console.print(f"  [yellow]⚠[/]  {msg}")
            elif level == "error":
                console.print(f"  [red]✗[/]  {msg}")
            else:
                console.print(f"  [dim]ℹ[/]  {msg}")

    # Commands
    if commands:
        console.print()
        console.print(f"  [bold]Commands to run:[/]")
        for cmd in commands:
            if cmd.impact == Impact.SAFE:
                console.print(f"    [green]✓[/] {cmd.command}")
            elif cmd.impact == Impact.CAUTION:
                console.print(f"    [yellow]⚠[/] {cmd.command}")
            elif cmd.impact == Impact.BLOCKED:
                console.print(f"    [red]✗[/] {cmd.command}  [dim](blocked)[/]")

    if spec.reasoning:
        console.print()
        console.print(f"  [dim]{spec.reasoning}[/]")

    while True:
        console.print()
        response = console.input("[yellow]Proceed?[/] [dim]\\[yes/no/edit/explain][/] → ").strip().lower()

        if response in ("yes", "y", ""):
            return True
        elif response in ("no", "n"):
            return False
        elif response in ("edit", "e"):
            return "edit"
        elif response in ("explain", "ex"):
            return "explain"
        else:
            console.print(f"  [dim]Choose yes, no, edit, or explain.[/]")


def _parse_package_string(pkg_str: str):
    """Parse a package string like 'requests>=2.28' into a PackageSpec."""
    import re
    from shellock_core.core.schemas import PackageSpec

    pkg_str = pkg_str.strip()
    if not pkg_str:
        return None
    # Split name from version specifier (==, >=, <=, !=, ~=, >, <)
    match = re.match(r'^([A-Za-z0-9_\-\.]+)(\[.*?\])?((?:[><=!~]+.*)?)$', pkg_str)
    if match:
        name = match.group(1)
        extras_str = match.group(2) or ""
        version = match.group(3).strip() or None
        extras = [e.strip() for e in extras_str.strip("[]").split(",") if e.strip()] if extras_str else []
        return PackageSpec(name=name, version=version, extras=extras)
    return PackageSpec(name=pkg_str)


def _sanitize_name(raw: str) -> str:
    """Sanitize a user-entered env name to kebab-case."""
    import re
    s = raw.strip().lower()
    s = re.sub(r"[^a-z0-9._-]", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-") or "shellock-env"


def prompt_edit_spec(spec: EnvSpec) -> EnvSpec:
    """Let the user interactively edit key fields of the spec.

    Returns the modified spec.
    """
    if _plain_mode():
        return _plain_edit_spec(spec)

    from pathlib import Path as _Path

    from rich.console import Console

    console = Console()
    console.print()
    console.print("  [bold]Edit environment[/]  [dim](press Enter to keep current value)[/]")
    console.print()

    # Name
    new_id = console.input(f"  [bold]Name[/]     [{spec.env_id}]: ").strip()
    if new_id:
        spec.env_id = _sanitize_name(new_id)
        spec.env_path = str(_Path.home() / ".shellock" / "envs" / spec.env_id)

    # runtime_version
    new_runtime = console.input(f"  [bold]Runtime[/]  [{spec.runtime_version or 'auto'}]: ").strip()
    if new_runtime:
        spec.runtime_version = new_runtime

    # packages
    current_pkgs = ", ".join(p.to_install_string() for p in spec.packages) if spec.packages else "none"
    console.print(f"  [dim]Packages: {current_pkgs}[/]")
    new_pkgs = console.input("  [bold]Packages[/] (comma-separated, or Enter to keep): ").strip()
    if new_pkgs:
        parsed = [_parse_package_string(p) for p in new_pkgs.split(",")]
        spec.packages = [p for p in parsed if p is not None]

    console.print()
    console.print(f"  [green]✓[/] Name: [bold]{spec.env_id}[/]")
    return spec


def show_explain(spec: EnvSpec) -> None:
    """Show a detailed explanation of the spec choices."""
    if _plain_mode():
        print(f"\n--- Explanation ---")
        if spec.reasoning:
            print(f"  {spec.reasoning}")
        else:
            print("  No LLM reasoning available (spec was generated from templates).")
        print(f"\n  Module: {spec.module}")
        if spec.runtime_version:
            print(f"  Runtime {spec.runtime_version} was chosen based on your description.")
        if spec.packages:
            print(f"  Packages: {', '.join(p.name for p in spec.packages)}")
        if spec.env_path:
            print(f"  Path: {spec.env_path}")
        print()
        try:
            input("Press Enter to continue...")
        except (EOFError, OSError):
            pass
        return

    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    console.print()

    explanation_parts = []
    if spec.reasoning:
        explanation_parts.append(f"[bold]LLM Reasoning:[/]\n  {spec.reasoning}")
    else:
        explanation_parts.append("[dim]No LLM reasoning available (spec was generated from templates).[/]")

    explanation_parts.append(f"\n[bold]Module:[/] {spec.module}")

    if spec.runtime_version:
        explanation_parts.append(
            f"[bold]Runtime:[/] Python {spec.runtime_version} — chosen based on your description."
        )

    if spec.packages:
        pkg_lines = ["\n[bold]Packages:[/]"]
        for p in spec.packages:
            reason = f" [dim]— {p.reason}[/]" if p.reason else ""
            pkg_lines.append(f"  • {p.to_install_string()}{reason}")
        explanation_parts.append("\n".join(pkg_lines))

    if spec.env_path:
        explanation_parts.append(f"[bold]Environment path:[/] {spec.env_path}")

    console.print(
        Panel(
            "\n".join(explanation_parts),
            title="Explanation",
            border_style="blue",
            padding=(1, 2),
        )
    )
    try:
        console.input("[dim]Press Enter to continue...[/]")
    except (EOFError, OSError):
        pass


def show_spec_diff(old_spec: EnvSpec, new_spec: EnvSpec) -> None:
    """Show what changed between the existing spec and the new one."""
    old_pkgs = {p.name for p in (old_spec.packages or [])}
    new_pkgs = {p.name for p in (new_spec.packages or [])}
    added = sorted(new_pkgs - old_pkgs)
    removed = sorted(old_pkgs - new_pkgs)
    name_changed = old_spec.env_id != new_spec.env_id
    runtime_changed = old_spec.runtime_version != new_spec.runtime_version

    if _plain_mode():
        print("\n--- Re-init diff (existing spec found) ---")
        if name_changed:
            print(f"  Name:    {old_spec.env_id} → {new_spec.env_id}")
        if runtime_changed:
            print(f"  Runtime: {old_spec.runtime_version} → {new_spec.runtime_version}")
        if added:
            print(f"  + Added: {', '.join(added)}")
        if removed:
            print(f"  - Removed: {', '.join(removed)}")
        if not any([name_changed, runtime_changed, added, removed]):
            print("  (no changes detected)")
        print()
        return

    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    console.print()
    lines = []
    if name_changed:
        lines.append(f"[dim]Name:[/]    [yellow]{old_spec.env_id}[/] → [green]{new_spec.env_id}[/]")
    if runtime_changed:
        lines.append(f"[dim]Runtime:[/] [yellow]{old_spec.runtime_version}[/] → [green]{new_spec.runtime_version}[/]")
    for p in added:
        lines.append(f"[green]+ {p}[/]")
    for p in removed:
        lines.append(f"[red]- {p}[/]")
    if not lines:
        lines.append("[dim]No changes detected.[/]")
    console.print(
        Panel(
            "\n".join(lines),
            title="[yellow]Re-init — existing spec found[/]",
            border_style="yellow",
            padding=(1, 2),
        )
    )


def show_plan_preview(
    spec: EnvSpec,
    commands: list[Command],
    warnings: list[dict[str, Any]] | None = None,
) -> None:
    """Display the spec + commands without asking for approval (--yes mode)."""
    if _plain_mode():
        _plain_plan_display(spec, commands, warnings)
        return

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    console.print()
    console.print(
        Panel(
            f"[bold cyan]Environment Plan[/] — [dim]{spec.module}[/]  [green](auto-approved)[/]",
            border_style="cyan",
            padding=(0, 2),
        )
    )

    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column("Key", style="dim", width=16)
    table.add_column("Value")
    table.add_row("Name", f"[bold]{spec.env_id}[/]")
    if spec.runtime_version:
        table.add_row("Runtime", f"Python {spec.runtime_version}")
    if spec.packages:
        table.add_row("Packages", ", ".join(p.to_install_string() for p in spec.packages))
    if spec.env_path:
        table.add_row("Path", f"[dim]{spec.env_path}[/]")
    console.print(table)

    if warnings:
        for w in warnings:
            level = w.get("level", "info")
            msg = w.get("message", "")
            if level == "caution":
                console.print(f"  [yellow]⚠[/]  {msg}")
            elif level == "error":
                console.print(f"  [red]✗[/]  {msg}")
            else:
                console.print(f"  [dim]ℹ[/]  {msg}")

    if commands:
        console.print()
        for cmd in commands:
            if cmd.impact == Impact.SAFE:
                console.print(f"    [green]✓[/] {cmd.command}")
            elif cmd.impact == Impact.CAUTION:
                console.print(f"    [yellow]⚠[/] {cmd.command}")
            elif cmd.impact == Impact.BLOCKED:
                console.print(f"    [red]✗[/] {cmd.command}  [dim](blocked)[/]")

    console.print()



def show_diagnosis(result: DiagnosisResult) -> bool:
    """Display an error diagnosis and ask to apply the fix.

    Returns True if the user wants to apply the fix.
    """
    if _plain_mode():
        return _plain_diagnosis(result)

    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    console.print()

    if result.diagnosed and result.fix:
        method_color = {
            "introspection": "green",
            "knowledge_base": "blue",
            "llm": "yellow",
        }.get(result.method.value, "dim")

        console.print(
            Panel(
                f"[bold]Diagnosis[/] [dim]via[/] [{method_color}]{result.method.value}[/]",
                border_style=method_color,
                padding=(0, 2),
            )
        )

        fix = result.fix
        if "commands" in fix:
            for cmd in fix["commands"]:
                console.print(f"  [cyan]→[/] {cmd}")

        if "reasoning" in fix:
            console.print(f"\n  [dim]{fix['reasoning']}[/]")

        console.print()
        r = console.input("[yellow]Apply fix?[/] [dim]\\[yes/no][/] → ").strip().lower()
        return r in ("yes", "y", "")

    else:
        console.print(
            Panel(
                "[yellow]Shellock couldn't diagnose this error.[/]",
                border_style="yellow",
                padding=(0, 2),
            )
        )
        if result.suggestions:
            for s in result.suggestions:
                console.print(f"  [dim]→[/] {s}")
        if result.resources:
            console.print()
            for r in result.resources:
                console.print(f"  [blue]{r}[/]")

        return False


def show_history(actions: list[dict[str, Any]]) -> None:
    """Display the project's action history in a human-readable format."""
    if _plain_mode():
        _plain_history(actions)
        return

    from rich.console import Console

    console = Console()

    type_icons = {
        "init": ("green", "++"),
        "fix": ("yellow", "!!"),
        "add": ("cyan", "+ "),
        "remove": ("red", "- "),
        "rollback": ("magenta", "<-"),
    }

    console.print()
    console.print(f"  [bold]Project History[/]  [dim]({len(actions)} actions)[/]")
    console.print()

    for action in reversed(actions):
        a_type = action.get("type", "unknown")
        color, icon = type_icons.get(a_type, ("white", "? "))
        result = action.get("result", "")
        result_icon = "[green]OK[/]" if result == "success" else "[red]FAIL[/]"
        action_id = action.get("id", "—")
        timestamp = str(action.get("timestamp", ""))[:16].replace("T", " ")

        # Build a readable summary
        summary = ""
        env_name = ""
        if action.get("spec"):
            spec = action["spec"]
            env_name = spec.get("env_id", "")
            pkgs = spec.get("packages", [])
            if isinstance(pkgs, list):
                pkg_names = [p["name"] if isinstance(p, dict) else str(p) for p in pkgs[:5]]
                if pkg_names:
                    summary = ", ".join(pkg_names)
                    if len(pkgs) > 5:
                        summary += f" +{len(pkgs) - 5} more"
            env_path = spec.get("env_path", "")
            if env_path:
                summary += f"\n             [dim]path: {env_path}[/]"

        if action.get("trigger_error"):
            summary = action["trigger_error"][:80]

        if action.get("diagnosis_method"):
            summary += f"  [dim](via {action['diagnosis_method']})[/]"

        # Format the entry
        header = f"  [{color}]{icon}[/] [{color} bold]{a_type.upper()}[/]"
        if env_name:
            header += f"  [bold]{env_name}[/]"
        header += f"  {result_icon}  [dim]{timestamp}[/]  [dim]({action_id})[/]"

        console.print(header)
        if summary:
            console.print(f"             {summary}")
        console.print()


def show_profile(
    profile: UserProfile,
    history: ProjectHistory,
    spec: EnvSpec | None = None,
) -> None:
    """Display the learned profile and project error context."""
    profile_path = Path.home() / ".shellock" / "profile.json"
    if _plain_mode():
        _plain_profile(profile, history, profile_path, spec)
        return

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    console.print()

    sys_info = profile.system
    system_line = f"{sys_info.os or 'OS unknown'} - {sys_info.arch or 'arch unknown'}"
    shell_line = sys_info.shell or "shell unknown"
    pkg_managers = ", ".join(sys_info.package_managers) or "none detected"
    llm_provider = sys_info.llm_provider or "not configured"
    if sys_info.llm_model:
        llm_provider = f"{llm_provider} ({sys_info.llm_model})"

    panel_lines = [
        f"[dim]System:[/] {system_line}",
        f"[dim]Shell:[/] {shell_line}",
        f"[dim]Package managers:[/] {pkg_managers}",
        f"[dim]LLM provider:[/] {llm_provider}",
        f"[dim]LLM tier:[/] {sys_info.llm_tier.value}",
        f"[dim]Suggestion threshold:[/] {profile.suggestion_threshold} uses",
        f"[dim]Profile file:[/] {profile_path}",
    ]
    console.print(Panel("\n".join(panel_lines), title="Shellock profile", border_style="cyan"))

    cpu_line = sys_info.cpu_info or "unknown CPU"
    hardware_lines = [f"[dim]CPU:[/] {cpu_line}"]
    if sys_info.cpu_logical_cores is not None:
        hardware_lines.append(f"[dim]Logical cores:[/] {sys_info.cpu_logical_cores}")
    if sys_info.cpu_physical_cores is not None:
        hardware_lines.append(f"[dim]Physical cores:[/] {sys_info.cpu_physical_cores}")
    accel_tags = []
    if sys_info.gpu_info:
        accel_tags.append(sys_info.gpu_info)
    if sys_info.cuda_available:
        accel_tags.append("CUDA available")
    if sys_info.mps_available:
        accel_tags.append("MPS available")
    if accel_tags:
        hardware_lines.append(f"[dim]Accelerators:[/] {', '.join(accel_tags)}")
    else:
        hardware_lines.append("[dim]Accelerators:[/] CPU-only")
    console.print(Panel("\n".join(hardware_lines), title="Hardware overview", border_style="green"))

    if spec:
        pkg_display = ""
        if spec.packages:
            pkg_display = ", ".join(p.to_install_string() for p in spec.packages[:8])
            if len(spec.packages) > 8:
                pkg_display += f" [dim]+{len(spec.packages) - 8} more[/]"
        spec_table = Table(
            title="Active spec",
            border_style="blue",
            show_header=False,
            box=None,
            padding=(0, 1),
        )
        spec_table.add_column("Field", style="dim", width=12)
        spec_table.add_column("Value")
        spec_table.add_row("Env ID", spec.env_id)
        spec_table.add_row("Module", spec.module)
        if spec.runtime_version:
            spec_table.add_row("Runtime", spec.runtime_version)
        if pkg_display:
            spec_table.add_row("Packages", pkg_display)
        if spec.env_path:
            spec_table.add_row("Path", spec.env_path)
        console.print(spec_table)


def show_envs(envs_dir: Any) -> None:
    """List all Shellock environments with details."""
    from pathlib import Path
    import subprocess

    envs_path = Path(envs_dir)
    env_dirs = sorted(
        [d for d in envs_path.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )

    if _plain_mode():
        print("\n--- Shellock Environments ---\n")
        for env_dir in env_dirs:
            info = _get_env_info(env_dir)
            print(f"  {env_dir.name}")
            if info.get("python_version"):
                print(f"    Python:   {info['python_version']}")
            if info.get("packages"):
                print(f"    Packages: {', '.join(info['packages'][:8])}")
            print(f"    Path:     {env_dir}")
            print(f"    Activate: source {env_dir}/bin/activate")
            print()
        return

    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.print()

    table = Table(
        title="Shellock Environments",
        border_style="cyan",
        show_lines=True,
        pad_edge=True,
    )
    table.add_column("Name", style="bold cyan", min_width=15)
    table.add_column("Python", style="green", width=10)
    table.add_column("Packages", min_width=30)
    table.add_column("Activate", style="dim")

    for env_dir in env_dirs:
        info = _get_env_info(env_dir)

        python_ver = info.get("python_version", "?")

        pkgs = info.get("packages", [])
        if pkgs:
            pkg_display = ", ".join(pkgs[:8])
            if len(pkgs) > 8:
                pkg_display += f" [dim]+{len(pkgs) - 8} more[/]"
        else:
            pkg_display = "[dim]none[/]"

        is_windows = os.name == "nt"
        if is_windows:
            activate = f"{env_dir}\\Scripts\\activate"
        else:
            activate = f"source {env_dir}/bin/activate"

        table.add_row(
            env_dir.name,
            python_ver,
            pkg_display,
            activate,
        )

    console.print(table)
    console.print(f"\n  [dim]{len(env_dirs)} environment(s) found[/]")
    console.print(f"  [dim]Use:[/] shellock use <name> [dim]for details[/]\n")


def show_env_details(env_path: Any) -> None:
    """Show detailed info about a single environment."""
    from pathlib import Path

    env_dir = Path(env_path)
    info = _get_env_info(env_dir)

    if _plain_mode():
        print(f"\n--- Environment: {env_dir.name} ---")
        print(f"  Python:   {info.get('python_version', '?')}")
        print(f"  Path:     {env_dir}")
        if info.get("packages"):
            print(f"  Packages: {', '.join(info['packages'])}")
        print()
        return

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    console.print()
    console.print(
        Panel(
            f"[bold cyan]{env_dir.name}[/]",
            subtitle=f"[dim]{env_dir}[/]",
            border_style="cyan",
            padding=(0, 2),
        )
    )

    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column("Key", style="dim", width=14)
    table.add_column("Value")

    table.add_row("Python", info.get("python_version", "?"))
    table.add_row("Path", str(env_dir))

    pkgs = info.get("packages", [])
    if pkgs:
        # Show packages in rows of 5
        for i in range(0, len(pkgs), 5):
            label = "Packages" if i == 0 else ""
            chunk = ", ".join(pkgs[i : i + 5])
            table.add_row(label, chunk)
    else:
        table.add_row("Packages", "[dim]none installed[/]")

    console.print(table)
    console.print()


def _get_env_info(env_dir: Any) -> dict[str, Any]:
    """Extract info from a venv directory (Python version, installed packages)."""
    from pathlib import Path
    import subprocess

    env_dir = Path(env_dir)
    info: dict[str, Any] = {}

    # Read Python version from pyvenv.cfg
    cfg = env_dir / "pyvenv.cfg"
    if cfg.exists():
        for line in cfg.read_text().splitlines():
            if line.startswith("version"):
                info["python_version"] = line.split("=", 1)[1].strip()
                break

    # Get installed packages via pip list
    pip_path = env_dir / "bin" / "pip"
    if not pip_path.exists():
        pip_path = env_dir / "Scripts" / "pip.exe"

    if pip_path.exists():
        try:
            proc = subprocess.run(
                [str(pip_path), "list", "--format=columns"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0:
                lines = proc.stdout.strip().split("\n")
                # Skip header lines (Package / Version / ------ / ------)
                pkgs = []
                for line in lines[2:]:
                    parts = line.split()
                    if parts:
                        name = parts[0].lower()
                        # Skip pip/setuptools/wheel (boring defaults)
                        if name not in ("pip", "setuptools", "wheel"):
                            pkgs.append(parts[0])
                info["packages"] = pkgs
        except (subprocess.TimeoutExpired, FileNotFoundError):
            info["packages"] = []
    else:
        info["packages"] = []

    return info


def show_success(message: str) -> None:
    """Display a success message."""
    if _plain_mode():
        print(f"✓ {message}")
        return
    from rich.console import Console
    Console().print(f"  [green]✓[/] {message}")


def show_error(message: str) -> None:
    """Display an error message."""
    if _plain_mode():
        print(f"✗ {message}")
        return
    from rich.console import Console
    Console().print(f"  [red]✗[/] {message}")


def show_info(message: str) -> None:
    """Display an info message."""
    if _plain_mode():
        print(f"ℹ {message}")
        return
    from rich.console import Console
    Console().print(f"  [dim]→[/] {message}")


def show_warning(message: str) -> None:
    """Display a warning message."""
    if _plain_mode():
        print(f"⚠ {message}")
        return
    from rich.console import Console
    Console().print(f"  [yellow]⚠[/] {message}")


def show_rollback_plan(action_id: str, action_type: str, commands: list[str]) -> bool:
    """Show the rollback commands that will be executed and ask for confirmation.

    Returns True if the user confirms, False to abort.
    """
    if _plain_mode():
        print(f"\nRolling back action {action_id} ({action_type})")
        print("Commands to execute:")
        for cmd in commands:
            print(f"  ! {cmd}")
        r = input("\nProceed with rollback? [yes/no] → ").strip().lower()
        return r in ("yes", "y")

    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    console.print()
    console.print(
        Panel(
            f"[bold magenta]Rollback Plan[/] — undoing [bold]{action_id}[/] ({action_type})",
            border_style="magenta",
            padding=(0, 2),
        )
    )
    console.print()
    console.print("  [bold]Commands to execute:[/]")
    for cmd in commands:
        console.print(f"    [red]![/] {cmd}")
    console.print()
    response = console.input(
        "[yellow]Proceed with rollback?[/] [dim]\\[yes/no][/] → "
    ).strip().lower()
    return response in ("yes", "y")


def show_adaptive(axis: str, message: str) -> None:
    """Display an adaptive behaviour announcement — makes decisions scrutable."""
    tag = {"preferences": "ADAPT:prefs", "error-patterns": "ADAPT:errors", "system": "ADAPT:sys"}.get(axis, f"ADAPT:{axis}")
    if _plain_mode():
        print(f"  [{tag}] {message}")
        return
    from rich.console import Console
    Console().print(f"  [magenta][{tag}][/] {message}")


def prompt_activate(env_name: str) -> bool:
    """Ask whether to activate the new environment. Returns True to activate."""
    if _plain_mode():
        r = input(f"Activate '{env_name}' now? [yes/no] → ").strip().lower()
        return r in ("yes", "y", "")

    from rich.console import Console

    console = Console()
    console.print()
    r = console.input(
        f"  [green]Activate '{env_name}' now?[/] [dim]\\[yes/no][/] → "
    ).strip().lower()
    return r in ("yes", "y", "")


# ── Plain-mode fallbacks ────────────────────────────────────────


def _plain_edit_spec(spec: EnvSpec) -> EnvSpec:
    """Plain-mode spec editing."""
    from pathlib import Path as _Path

    print("\nEdit environment — press Enter to keep current value:")
    new_id = input(f"  Name     [{spec.env_id}]: ").strip()
    if new_id:
        spec.env_id = _sanitize_name(new_id)
        spec.env_path = str(_Path.home() / ".shellock" / "envs" / spec.env_id)
    new_runtime = input(f"  Runtime  [{spec.runtime_version or 'auto'}]: ").strip()
    if new_runtime:
        spec.runtime_version = new_runtime
    current_pkgs = ", ".join(p.to_install_string() for p in spec.packages) if spec.packages else "none"
    print(f"  Packages: {current_pkgs}")
    new_pkgs = input("  Packages (comma-separated, or Enter to keep): ").strip()
    if new_pkgs:
        parsed = [_parse_package_string(p) for p in new_pkgs.split(",")]
        spec.packages = [p for p in parsed if p is not None]
    print(f"  Name set to: {spec.env_id}\n")
    return spec


def _plain_plan_display(
    spec: EnvSpec,
    commands: list[Command],
    warnings: list[dict[str, Any]] | None = None,
) -> None:
    """Plain-text plan display without prompting (used by --yes mode)."""
    print(f"\n--- Environment Plan ({spec.module}) [auto-approved] ---")
    print(f"  Name:     {spec.env_id}")
    if spec.runtime_version:
        print(f"  Runtime:  {spec.runtime_version}")
    if spec.packages:
        pkgs = [p.to_install_string() for p in spec.packages]
        print(f"  Packages: {', '.join(pkgs)}")
    if spec.env_path:
        print(f"  Path:     {spec.env_path}")
    if warnings:
        for w in warnings:
            print(f"  [{w.get('level', 'info')}] {w.get('message', '')}")
    if commands:
        print("\n  Commands:")
        for cmd in commands:
            label = cmd.impact.value.upper()
            print(f"    [{label}] {cmd.command}")
    print()


def _plain_approval(
    spec: EnvSpec,
    commands: list[Command],
    warnings: list[dict[str, Any]] | None = None,
) -> bool | str:
    print(f"\n--- Environment Plan ({spec.module}) ---")
    print(f"  Name:     {spec.env_id}")
    if spec.runtime_version:
        print(f"  Runtime:  Python {spec.runtime_version}")
    if spec.packages:
        pkgs = [p.to_install_string() for p in spec.packages]
        print(f"  Packages: {', '.join(pkgs)}")
    if spec.env_path:
        print(f"  Path:     {spec.env_path}")
    if warnings:
        for w in warnings:
            print(f"  [{w.get('level', 'info')}] {w.get('message', '')}")
    if commands:
        print("\n  Commands:")
        for cmd in commands:
            label = cmd.impact.value.upper()
            print(f"    [{label}] {cmd.command}")
    if spec.reasoning:
        print(f"\n  {spec.reasoning}")
    print()
    while True:
        r = input("Proceed? [yes/no/edit/explain] → ").strip().lower()
        if r in ("yes", "y", ""):
            return True
        elif r in ("no", "n"):
            return False
        elif r in ("edit", "e"):
            return "edit"
        elif r in ("explain", "ex"):
            return "explain"
        else:
            print(f"  Choose yes, no, edit, or explain.")


def _plain_diagnosis(result: DiagnosisResult) -> bool:
    if result.diagnosed and result.fix:
        print(f"\nDiagnosis ({result.method.value}):")
        if "commands" in result.fix:
            for cmd in result.fix["commands"]:
                print(f"  → {cmd}")
        r = input("Apply fix? [yes/no] → ").strip().lower()
        return r in ("yes", "y", "")
    else:
        print("\nShellock couldn't diagnose this error.")
        for s in result.suggestions:
            print(f"  → {s}")
        return False


def _plain_history(actions: list[dict[str, Any]]) -> None:
    print("\n--- Project History ---")
    for a in actions:
        print(f"  {a.get('id', '—')}  {a.get('type', '?')}  {a.get('result', '')}  {str(a.get('timestamp', ''))[:19]}")
