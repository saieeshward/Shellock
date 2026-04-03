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


def prompt_edit_spec(spec: EnvSpec) -> EnvSpec:
    """Let the user interactively edit key fields of the spec.

    Returns the modified spec.
    """
    from shellock_core.core.schemas import PackageSpec

    if _plain_mode():
        return _plain_edit_spec(spec)

    from rich.console import Console

    console = Console()
    console.print()
    console.print("  [bold]Edit spec[/] — press Enter to keep current value, or type a new one.")
    console.print()

    # env_id
    new_id = console.input(f"  env_id [{spec.env_id}]: ").strip()
    if new_id:
        spec.env_id = new_id

    # runtime_version
    new_runtime = console.input(f"  runtime [{spec.runtime_version or 'auto'}]: ").strip()
    if new_runtime:
        spec.runtime_version = new_runtime

    # packages
    current_pkgs = ", ".join(p.to_install_string() for p in spec.packages) if spec.packages else "none"
    console.print(f"  [dim]Current packages: {current_pkgs}[/]")
    new_pkgs = console.input("  packages (comma-separated, or Enter to keep): ").strip()
    if new_pkgs:
        spec.packages = [
            PackageSpec(name=p.strip()) for p in new_pkgs.split(",") if p.strip()
        ]

    # Update env_path if env_id changed
    from pathlib import Path as _Path
    if new_id:
        spec.env_path = str(_Path.home() / ".shellock" / "envs" / spec.env_id)

    console.print()
    console.print("  [green]Spec updated.[/]")
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
        print()
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
        pkg_list = ", ".join(p.to_install_string() for p in spec.packages)
        explanation_parts.append(f"[bold]Packages:[/] {pkg_list}")

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
    from shellock_core.core.schemas import PackageSpec

    print("\nEdit spec — press Enter to keep current value:")
    new_id = input(f"  env_id [{spec.env_id}]: ").strip()
    if new_id:
        spec.env_id = new_id
    new_runtime = input(f"  runtime [{spec.runtime_version or 'auto'}]: ").strip()
    if new_runtime:
        spec.runtime_version = new_runtime
    current_pkgs = ", ".join(p.to_install_string() for p in spec.packages) if spec.packages else "none"
    print(f"  Current packages: {current_pkgs}")
    new_pkgs = input("  packages (comma-separated, or Enter to keep): ").strip()
    if new_pkgs:
        spec.packages = [
            PackageSpec(name=p.strip()) for p in new_pkgs.split(",") if p.strip()
        ]
    if new_id:
        from pathlib import Path as _Path
        spec.env_path = str(_Path.home() / ".shellock" / "envs" / spec.env_id)
    print("  Spec updated.\n")
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


def show_profile(profile: Any, error_frequency: dict[str, Any] | None = None) -> None:
    """Display the user model in full — the scrutability screen."""
    if _plain_mode():
        _plain_profile(profile, error_frequency)
        return

    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    console.print()
    console.print(
        Panel(
            "[bold cyan]User Model[/]  [dim](what Shellock has learned about you)[/]",
            border_style="cyan",
            padding=(0, 2),
        )
    )

    # System info
    sys_info = profile.system if hasattr(profile, "system") else {}
    sys_dict = sys_info.model_dump() if hasattr(sys_info, "model_dump") else dict(sys_info)
    console.print()
    console.print("  [bold]System[/]")
    console.print(f"    OS:        {sys_dict.get('os', '?')} ({sys_dict.get('arch', '?')})")
    console.print(f"    Shell:     {sys_dict.get('shell', '?')}")
    gpu = sys_dict.get("gpu", "none")
    vram = sys_dict.get("vram_gb")
    gpu_label = f"{gpu}" + (f" ({vram}GB VRAM)" if vram else "")
    console.print(f"    GPU:       {gpu_label}")
    tier = sys_dict.get("llm_tier", "template")
    provider = sys_dict.get("llm_provider") or "—"
    model = sys_dict.get("llm_model") or "—"
    console.print(f"    LLM tier:  {tier} ({provider} / {model})")

    # Preferences
    prefs = profile.preferences if hasattr(profile, "preferences") else {}
    threshold = profile.suggestion_threshold if hasattr(profile, "suggestion_threshold") else 3
    console.print()
    console.print(f"  [bold]Preferences[/]  [dim](suggest after {threshold} uses)[/]")
    if prefs:
        for category, tools in prefs.items():
            console.print(f"    [dim]{category}:[/]")
            for tool, count in sorted(tools.items(), key=lambda x: -x[1]):
                bar = "█" * min(count, 12)
                will_suggest = " [green]← auto-suggest[/]" if count >= threshold else ""
                console.print(f"      {tool:<20} {bar} {count} uses{will_suggest}")
    else:
        console.print("    [dim]No preferences recorded yet.[/]")

    # Rejected suggestions
    rejected = profile.rejected_suggestions if hasattr(profile, "rejected_suggestions") else []
    if rejected:
        console.print()
        console.print("  [bold]Rejected suggestions[/]")
        for r in rejected:
            console.print(f"    [dim]✗ {r}[/]")

    # Error patterns from current project history
    if error_frequency:
        console.print()
        console.print(f"  [bold]Error patterns seen[/]  [dim]({len(error_frequency)} distinct)[/]")
        for fp, data in list(error_frequency.items())[:10]:
            count = data.get("count", 0)
            pattern = data.get("pattern", "")[:60]
            worked = len(data.get("fixes_that_worked", []))
            fix_label = f"  [green]{worked} fix(es) learned[/]" if worked else ""
            console.print(f"    [dim][{fp}][/] {pattern!r} ×{count}{fix_label}")
    else:
        console.print()
        console.print("  [dim]No error patterns recorded for this project.[/]")

    # Timestamps
    created = str(getattr(profile, "created_at", "?"))[:10]
    updated = str(getattr(profile, "last_updated", "?"))[:10]
    console.print()
    console.print(f"  [dim]Profile created: {created}  ·  Last updated: {updated}[/]")
    console.print(f"  [dim]Stored at: ~/.shellock/profile.json[/]")
    console.print()


def prompt_web_search(query: str) -> bool:
    """Ask the user if they want to use web search to enrich package resolution.

    Returns True if the user approves.
    """
    if _plain_mode():
        r = input(f"  Use web search to find packages for '{query}'? [yes/no] → ").strip().lower()
        return r in ("yes", "y")

    from rich.console import Console
    console = Console()
    console.print()
    console.print(f"  [dim]Web search can find niche packages Shellock doesn't know about.[/]")
    r = console.input(
        f"  [yellow]Search the web for packages matching '{query}'?[/] [dim]\\[yes/no][/] → "
    ).strip().lower()
    return r in ("yes", "y")


def _plain_profile(profile: Any, error_frequency: dict[str, Any] | None = None) -> None:
    print("\n--- User Model ---\n")
    sys_dict = profile.system.model_dump() if hasattr(profile.system, "model_dump") else {}
    print(f"  OS:     {sys_dict.get('os', '?')} ({sys_dict.get('arch', '?')})")
    print(f"  Shell:  {sys_dict.get('shell', '?')}")
    print(f"  GPU:    {sys_dict.get('gpu', 'none')}")
    print(f"  LLM:    {sys_dict.get('llm_tier', 'template')}")
    print()
    threshold = getattr(profile, "suggestion_threshold", 3)
    print(f"  Preferences (suggest after {threshold} uses):")
    for cat, tools in getattr(profile, "preferences", {}).items():
        print(f"    {cat}:")
        for tool, count in sorted(tools.items(), key=lambda x: -x[1]):
            flag = " [auto-suggest]" if count >= threshold else ""
            print(f"      {tool}: {count} uses{flag}")
    rejected = getattr(profile, "rejected_suggestions", [])
    if rejected:
        print(f"\n  Rejected: {', '.join(rejected)}")
    if error_frequency:
        print(f"\n  Error patterns ({len(error_frequency)}):")
        for fp, data in list(error_frequency.items())[:10]:
            print(f"    [{fp}] {data.get('pattern', '')[:50]!r} ×{data.get('count', 0)}")
    print()
