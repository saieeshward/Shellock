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
from typing import Any

from shellock_core.core.schemas import Command, DiagnosisResult, EnvSpec, Impact


def _plain_mode() -> bool:
    """Check if Rich formatting is disabled."""
    return os.environ.get("SHELLOCK_PLAIN", "").strip() in ("1", "true", "yes")


def show_spec_approval(spec: EnvSpec, warnings: list[dict[str, Any]] | None = None) -> bool:
    """Display the environment spec for user approval.

    Returns True if the user approves, False otherwise.
    """
    if _plain_mode():
        return _plain_spec_approval(spec, warnings)

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    console = Console()
    console.print()

    # Header
    console.print(
        Panel(
            f"[bold cyan]Environment Preview[/] — [dim]{spec.module}[/]",
            border_style="cyan",
            padding=(0, 2),
        )
    )

    # Spec details table
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column("Key", style="dim", width=16)
    table.add_column("Value")

    table.add_row("env_id", f"[bold]{spec.env_id}[/]")
    table.add_row("module", spec.module)

    if spec.runtime_version:
        table.add_row("runtime", spec.runtime_version)

    if spec.packages:
        pkg_strs = [p.to_install_string() for p in spec.packages]
        table.add_row("packages", ", ".join(pkg_strs))

    if spec.env_path:
        table.add_row("env path", spec.env_path)

    if spec.env_vars:
        vars_str = ", ".join(f"{k}={v}" for k, v in spec.env_vars.items())
        table.add_row("env vars", vars_str)

    if spec.post_hooks:
        table.add_row("post hooks", ", ".join(spec.post_hooks))

    console.print(table)

    # Warnings from validation
    if warnings:
        console.print()
        for w in warnings:
            level = w.get("level", "info")
            msg = w.get("message", "")
            if level == "caution":
                console.print(f"  [yellow]⚠ CAUTION[/]  {msg}")
            elif level == "error":
                console.print(f"  [red]✗ ERROR[/]    {msg}")
            else:
                console.print(f"  [dim]ℹ INFO[/]     {msg}")

    # Reasoning (if available)
    if spec.reasoning:
        console.print()
        console.print(f"  [dim]Reasoning: {spec.reasoning}[/]")

    # Approval prompt
    console.print()
    response = console.input("[yellow]Apply?[/] [dim]\\[yes/no/edit/explain][/] → ").strip().lower()
    return response in ("yes", "y", "")


def show_spec_preview(spec: EnvSpec, warnings: list[dict[str, Any]] | None = None) -> None:
    """Display the spec without asking for approval (--yes mode)."""
    if _plain_mode():
        _plain_spec_approval(spec, warnings)  # reuse display, ignore return
        return

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    console.print()
    console.print(
        Panel(
            f"[bold cyan]Environment Preview[/] — [dim]{spec.module}[/]  [green](auto-approved)[/]",
            border_style="cyan",
            padding=(0, 2),
        )
    )

    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column("Key", style="dim", width=16)
    table.add_column("Value")
    table.add_row("env_id", f"[bold]{spec.env_id}[/]")
    table.add_row("module", spec.module)
    if spec.runtime_version:
        table.add_row("runtime", spec.runtime_version)
    if spec.packages:
        table.add_row("packages", ", ".join(p.to_install_string() for p in spec.packages))
    if spec.env_path:
        table.add_row("env path", spec.env_path)
    console.print(table)

    if warnings:
        for w in warnings:
            level = w.get("level", "info")
            msg = w.get("message", "")
            if level == "caution":
                console.print(f"  [yellow]⚠ CAUTION[/]  {msg}")
            elif level == "error":
                console.print(f"  [red]✗ ERROR[/]    {msg}")
            else:
                console.print(f"  [dim]ℹ INFO[/]     {msg}")

    if spec.reasoning:
        console.print(f"\n  [dim]Reasoning: {spec.reasoning}[/]")
    console.print()


def show_commands_preview(commands: list[Command]) -> None:
    """Display commands without asking for approval (--yes mode)."""
    if _plain_mode():
        for cmd in commands:
            print(f"  [{cmd.impact.value.upper()}] {cmd.command} — {cmd.description}")
        return

    from rich.console import Console

    console = Console()
    console.print()
    for cmd in commands:
        if cmd.impact == Impact.SAFE:
            console.print(f"  [green]✓ SAFE[/]     {cmd.command}  [dim]({cmd.description})[/]")
        elif cmd.impact == Impact.CAUTION:
            console.print(f"  [yellow]⚠ CAUTION[/]  {cmd.command}  [dim]({cmd.description})[/]")
        elif cmd.impact == Impact.BLOCKED:
            console.print(f"  [red]✗ BLOCKED[/]  {cmd.command}  [dim]({cmd.description})[/]")
    console.print()


def show_commands(commands: list[Command]) -> tuple[bool, bool]:
    """Display commands with impact classification.

    Returns (approve_safe, approve_caution) booleans.
    """
    if _plain_mode():
        return _plain_commands(commands)

    from rich.console import Console

    console = Console()
    console.print()

    safe_cmds = [c for c in commands if c.impact == Impact.SAFE]
    caution_cmds = [c for c in commands if c.impact == Impact.CAUTION]
    blocked_cmds = [c for c in commands if c.impact == Impact.BLOCKED]

    for cmd in safe_cmds:
        console.print(f"  [green]✓ SAFE[/]     {cmd.command}  [dim]({cmd.description})[/]")

    for cmd in caution_cmds:
        console.print(f"  [yellow]⚠ CAUTION[/]  {cmd.command}  [dim]({cmd.description})[/]")

    for cmd in blocked_cmds:
        console.print(f"  [red]✗ BLOCKED[/]  {cmd.command}  [dim]({cmd.description})[/]")

    console.print()

    approve_safe = True
    approve_caution = False

    if safe_cmds:
        r = console.input("[green]Run safe commands?[/] [dim]\\[yes/no][/] → ").strip().lower()
        approve_safe = r in ("yes", "y", "")

    if caution_cmds:
        r = console.input("[yellow]Run cautioned commands?[/] [dim]\\[yes/no/explain][/] → ").strip().lower()
        approve_caution = r in ("yes", "y")

    return approve_safe, approve_caution


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
    """Display the project's action history."""
    if _plain_mode():
        _plain_history(actions)
        return

    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Project History", border_style="dim")
    table.add_column("ID", style="dim", width=12)
    table.add_column("Type", width=10)
    table.add_column("Result", width=10)
    table.add_column("Timestamp", width=20)
    table.add_column("Details", max_width=40)

    type_colors = {
        "init": "green",
        "fix": "yellow",
        "add": "cyan",
        "remove": "red",
        "rollback": "magenta",
    }

    for action in actions:
        a_type = action.get("type", "unknown")
        color = type_colors.get(a_type, "white")
        result = action.get("result", "")
        result_style = "green" if result == "success" else "red"

        details = ""
        if action.get("trigger_error"):
            details = action["trigger_error"][:40]
        elif action.get("spec") and action["spec"].get("packages"):
            pkgs = action["spec"]["packages"]
            if isinstance(pkgs, list):
                names = [p["name"] if isinstance(p, dict) else str(p) for p in pkgs[:3]]
                details = ", ".join(names)

        table.add_row(
            action.get("id", "—"),
            f"[{color}]{a_type}[/]",
            f"[{result_style}]{result}[/]",
            str(action.get("timestamp", "—"))[:19],
            details,
        )

    console.print(table)


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


# ── Plain-mode fallbacks ────────────────────────────────────────


def _plain_spec_approval(spec: EnvSpec, warnings: list[dict[str, Any]] | None = None) -> bool:
    print(f"\n--- Environment Preview ({spec.module}) ---")
    print(f"  env_id:   {spec.env_id}")
    print(f"  module:   {spec.module}")
    if spec.runtime_version:
        print(f"  runtime:  {spec.runtime_version}")
    if spec.packages:
        pkgs = [p.to_install_string() for p in spec.packages]
        print(f"  packages: {', '.join(pkgs)}")
    if spec.env_path:
        print(f"  env path: {spec.env_path}")
    if warnings:
        for w in warnings:
            print(f"  [{w.get('level', 'info')}] {w.get('message', '')}")
    if spec.reasoning:
        print(f"  reasoning: {spec.reasoning}")
    print()
    r = input("Apply? [yes/no] → ").strip().lower()
    return r in ("yes", "y", "")


def _plain_commands(commands: list[Command]) -> tuple[bool, bool]:
    for cmd in commands:
        label = cmd.impact.value.upper()
        print(f"  [{label}] {cmd.command} — {cmd.description}")
    r = input("Run? [yes/no] → ").strip().lower()
    return r in ("yes", "y", ""), False


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
