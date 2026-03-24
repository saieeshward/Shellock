"""Dispatcher — executes approved commands.

This is the only place in Shellock that runs shell commands.
Every command is checked against the active module's allowlist
and blocked patterns before execution.  Commands are run via
subprocess, never via eval/exec.

The dispatcher:
    1. Validates commands against module allowlist
    2. Classifies impact (safe/caution/blocked)
    3. Runs approved commands sequentially
    4. Captures stdout/stderr for the audit trail
    5. Returns structured results for error handling
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shellock_core.core.schemas import Command, Impact

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a single command execution."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    success: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout[:500],  # truncate for audit trail
            "stderr": self.stderr[:1000],
            "success": self.success,
        }


@dataclass
class DispatchResult:
    """Result of dispatching a full command list."""

    results: list[CommandResult] = field(default_factory=list)
    all_succeeded: bool = True
    first_error: CommandResult | None = None

    @property
    def failed_stderr(self) -> str | None:
        if self.first_error:
            return self.first_error.stderr
        return None


def validate_commands(
    commands: list[Command],
    allowed_commands: list[str],
    blocked_patterns: list[str],
) -> list[Command]:
    """Check commands against module allowlist and blocked patterns.

    Returns the commands with impact updated to BLOCKED for any
    that fail validation.  Blocked commands are never executed.
    """
    validated = []

    for cmd in commands:
        # Check blocked patterns first (hard reject)
        blocked = False
        for pattern in blocked_patterns:
            if re.search(pattern, cmd.command):
                logger.warning("BLOCKED: '%s' matches blocked pattern '%s'", cmd.command, pattern)
                validated.append(Command(
                    command=cmd.command,
                    impact=Impact.BLOCKED,
                    description=f"BLOCKED: matches safety pattern '{pattern}'",
                    rollback_command=cmd.rollback_command,
                ))
                blocked = True
                break

        if blocked:
            continue

        # Check allowlist (command or its basename must match a prefix)
        # Handles full paths like /Users/.../bin/pip install → matches "pip install"
        allowed = False
        cmd_str = cmd.command.strip()
        for prefix in allowed_commands:
            if cmd_str.startswith(prefix):
                allowed = True
                break
            # Check if the basename of the first token matches
            # e.g. "/path/to/bin/pip install foo" → "pip install foo"
            parts = cmd_str.split(None, 1)
            if parts:
                basename_cmd = Path(parts[0]).name
                rest = parts[1] if len(parts) > 1 else ""
                normalized = f"{basename_cmd} {rest}".strip()
                if normalized.startswith(prefix):
                    allowed = True
                    break

        if not allowed:
            logger.warning("BLOCKED: '%s' not in module allowlist", cmd.command)
            validated.append(Command(
                command=cmd.command,
                impact=Impact.BLOCKED,
                description=f"BLOCKED: not in module's allowed commands",
                rollback_command=cmd.rollback_command,
            ))
        else:
            validated.append(cmd)

    return validated


def execute_commands(
    commands: list[Command],
    cwd: str | None = None,
    env_override: dict[str, str] | None = None,
    dry_run: bool = False,
) -> DispatchResult:
    """Execute a list of approved commands sequentially.

    Skips any commands with impact=BLOCKED.  Stops on first failure
    and returns the error for diagnosis.

    If *dry_run* is True, returns what would happen without executing.
    """
    result = DispatchResult()
    work_dir = cwd or os.getcwd()

    # Build environment: inherit current env + overrides
    env = os.environ.copy()
    if env_override:
        env.update(env_override)

    # Progress callback for UI
    total = sum(1 for c in commands if c.impact != Impact.BLOCKED)
    step = 0

    for cmd in commands:
        if cmd.impact == Impact.BLOCKED:
            logger.info("Skipping blocked command: %s", cmd.command)
            continue

        step += 1

        if dry_run:
            result.results.append(CommandResult(
                command=cmd.command,
                exit_code=0,
                stdout="[DRY RUN] Would execute",
                stderr="",
                success=True,
            ))
            continue

        # Show progress
        _show_progress(step, total, cmd.description or cmd.command)
        logger.info("Executing: %s", cmd.command)
        cmd_result = _run_command(cmd.command, work_dir, env)
        result.results.append(cmd_result)

        if not cmd_result.success:
            result.all_succeeded = False
            result.first_error = cmd_result
            _show_step_result(False, cmd.description or cmd.command)
            logger.error(
                "Command failed (exit %d): %s\nstderr: %s",
                cmd_result.exit_code, cmd.command, cmd_result.stderr[:200],
            )
            break  # stop on first failure
        else:
            _show_step_result(True, cmd.description or cmd.command)

    return result


def _run_command(
    command: str,
    cwd: str,
    env: dict[str, str],
    timeout: int = 300,
) -> CommandResult:
    """Run a single shell command with live output streaming."""
    import io
    import select
    import sys
    import threading

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        def _read_stream(stream: io.TextIOBase, buf: list[str]) -> None:
            for line in iter(stream.readline, ""):
                buf.append(line)
                # Stream live to terminal (dimmed)
                try:
                    from rich.console import Console
                    Console().print(f"    [dim]{line.rstrip()}[/]")
                except ImportError:
                    print(f"    {line.rstrip()}")

        t_out = threading.Thread(target=_read_stream, args=(proc.stdout, stdout_lines))
        t_err = threading.Thread(target=_read_stream, args=(proc.stderr, stderr_lines))
        t_out.start()
        t_err.start()

        proc.wait(timeout=timeout)
        t_out.join(timeout=5)
        t_err.join(timeout=5)

        return CommandResult(
            command=command,
            exit_code=proc.returncode,
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
            success=proc.returncode == 0,
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        return CommandResult(
            command=command,
            exit_code=-1,
            stdout="",
            stderr=f"Command timed out after {timeout}s",
            success=False,
        )
    except Exception as e:
        return CommandResult(
            command=command,
            exit_code=-1,
            stdout="",
            stderr=str(e),
            success=False,
        )


def _show_progress(step: int, total: int, description: str) -> None:
    """Show execution progress."""
    try:
        from rich.console import Console
        Console().print(f"  [dim][{step}/{total}][/] {description}...", end="")
    except ImportError:
        print(f"  [{step}/{total}] {description}...", end="")


def _show_step_result(success: bool, description: str) -> None:
    """Show step completion."""
    try:
        from rich.console import Console
        icon = "[green]done[/]" if success else "[red]failed[/]"
        Console().print(f" {icon}")
    except ImportError:
        label = "done" if success else "failed"
        print(f" {label}")
