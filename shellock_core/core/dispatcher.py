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

        # Check allowlist (command prefix must match)
        allowed = False
        for prefix in allowed_commands:
            if cmd.command.strip().startswith(prefix):
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

    for cmd in commands:
        if cmd.impact == Impact.BLOCKED:
            logger.info("Skipping blocked command: %s", cmd.command)
            continue

        if dry_run:
            result.results.append(CommandResult(
                command=cmd.command,
                exit_code=0,
                stdout="[DRY RUN] Would execute",
                stderr="",
                success=True,
            ))
            continue

        logger.info("Executing: %s", cmd.command)
        cmd_result = _run_command(cmd.command, work_dir, env)
        result.results.append(cmd_result)

        if not cmd_result.success:
            result.all_succeeded = False
            result.first_error = cmd_result
            logger.error(
                "Command failed (exit %d): %s\nstderr: %s",
                cmd_result.exit_code, cmd.command, cmd_result.stderr[:200],
            )
            break  # stop on first failure

    return result


def _run_command(
    command: str,
    cwd: str,
    env: dict[str, str],
    timeout: int = 300,
) -> CommandResult:
    """Run a single shell command and capture output."""
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CommandResult(
            command=command,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            success=proc.returncode == 0,
        )
    except subprocess.TimeoutExpired:
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
