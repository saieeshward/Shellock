"""Node.js ecosystem module.

Handles Node.js version management, npm/yarn/pnpm package installation,
and Node-specific error diagnosis.

Uses Node's own introspection (npm ls --json, node -e require)
as the first line of defence.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from shellock_core.module_base import ShellockModule


class NodeModule(ShellockModule):

    name = "node"
    description = "Node.js environments, npm/yarn/pnpm packages, and version management"

    triggers = [
        "package.json",
        ".nvmrc",
        ".node-version",
        "yarn.lock",
        "pnpm-lock.yaml",
        "package-lock.json",
    ]

    allowed_commands = [
        "npm install",
        "npm uninstall",
        "npm init",
        "npm ls",
        "npm run",
        "npm ci",
        "yarn install",
        "yarn add",
        "yarn remove",
        "pnpm install",
        "pnpm add",
        "pnpm remove",
        "nvm install",
        "nvm use",
        "node -e",
        "npx",
    ]

    blocked_patterns = [
        r"sudo\s+",
        r"rm\s+-rf\s+/",
        r"npm\s+publish",  # don't accidentally publish
        r"\|\s*sh$",
        r"\|\s*bash$",
    ]

    suggestable_tools = [
        "typescript", "eslint", "prettier", "jest",
        "vitest", "nodemon", "ts-node", "tsx",
    ]

    # ── Detection ───────────────────────────────────────────────

    def detect(self, project_path: str) -> bool:
        path = Path(project_path)
        return any((path / trigger).exists() for trigger in self.triggers)

    # ── Onboarding ──────────────────────────────────────────────

    def onboarding_questions(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "node_pkg_manager",
                "question": "Preferred Node package manager?",
                "options": ["npm", "yarn", "pnpm"],
                "default": "npm",
            },
        ]

    # ── System introspection ────────────────────────────────────

    def introspect(self, project_path: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "node_available": shutil.which("node") is not None,
            "node_version": None,
            "npm_version": None,
            "nvm_available": False,
            "package_managers": [],
            "installed_packages": {},
        }

        # Node version
        if result["node_available"]:
            try:
                proc = subprocess.run(
                    ["node", "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                if proc.returncode == 0:
                    result["node_version"] = proc.stdout.strip()
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        # npm version
        if shutil.which("npm"):
            result["package_managers"].append("npm")
            try:
                proc = subprocess.run(
                    ["npm", "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                if proc.returncode == 0:
                    result["npm_version"] = proc.stdout.strip()
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        for mgr in ["yarn", "pnpm"]:
            if shutil.which(mgr):
                result["package_managers"].append(mgr)

        # nvm
        nvm_dir = Path.home() / ".nvm"
        result["nvm_available"] = nvm_dir.is_dir()

        # Read package.json if exists
        pkg_json = Path(project_path) / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text())
                result["package_name"] = data.get("name")
                result["dependencies"] = list(data.get("dependencies", {}).keys())
                result["dev_dependencies"] = list(data.get("devDependencies", {}).keys())
            except (json.JSONDecodeError, IOError):
                pass

        # Installed packages via npm ls
        node_modules = Path(project_path) / "node_modules"
        if node_modules.is_dir():
            try:
                proc = subprocess.run(
                    ["npm", "ls", "--json", "--depth=0"],
                    capture_output=True, text=True, timeout=10,
                    cwd=project_path,
                )
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    deps = data.get("dependencies", {})
                    result["installed_packages"] = {
                        name: info.get("version", "unknown")
                        for name, info in deps.items()
                    }
            except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
                pass

        return result

    # ── Spec generation ─────────────────────────────────────────

    def build_spec(self, description: str, context: dict[str, Any]) -> dict[str, Any]:
        packages = self._parse_packages_from_description(description)

        words = re.findall(r'\w+', description.lower())
        env_id = f"node-{'-'.join(words[:3])}" if words else "node-default"

        # Detect Node version from description
        runtime = None
        version_match = re.search(r'node\s*(\d+)', description, re.IGNORECASE)
        if version_match:
            runtime = version_match.group(1)

        return {
            "env_id": env_id,
            "module": "node",
            "runtime_version": runtime,
            "packages": [{"name": p} for p in packages],
            "reasoning": f"Parsed from description: '{description}'",
        }

    def validate_spec(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        warnings = []
        introspection = self.introspect(".")

        if not introspection.get("node_available"):
            warnings.append({
                "level": "error",
                "message": "Node.js is not installed on this system",
                "suggestion": "Install via nvm, brew, or https://nodejs.org",
            })

        return warnings

    # ── Command dispatch ────────────────────────────────────────

    def dispatch(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        commands = []
        packages = spec.get("packages", [])

        # Initialize package.json if needed
        pkg_json = Path(".") / "package.json"
        if not pkg_json.exists():
            commands.append({
                "command": "npm init -y",
                "impact": "safe",
                "description": "Initialize package.json",
            })

        # Install packages
        if packages:
            pkg_names = []
            for p in packages:
                if isinstance(p, dict):
                    name = p.get("name", "")
                    version = p.get("version")
                    pkg_names.append(f"{name}@{version}" if version else name)
                else:
                    pkg_names.append(str(p))

            commands.append({
                "command": f"npm install {' '.join(pkg_names)}",
                "impact": "safe",
                "description": f"Install: {', '.join(pkg_names)}",
                "rollback_command": f"npm uninstall {' '.join(pkg_names)}",
            })

        return commands

    # ── Error handling ──────────────────────────────────────────

    def diagnose(self, stderr: str, context: dict[str, Any]) -> dict[str, Any] | None:
        # ERESOLVE — peer dependency conflict
        if "ERESOLVE" in stderr or "peer dep" in stderr.lower():
            return {
                "action": "install",
                "commands": ["npm install --legacy-peer-deps"],
                "reasoning": "Peer dependency conflict. Using --legacy-peer-deps to resolve.",
            }

        # Module not found
        match = re.search(r"Cannot find module ['\"](\S+)['\"]", stderr)
        if match:
            module_name = match.group(1)
            if not module_name.startswith("."):
                return {
                    "action": "install",
                    "package": module_name,
                    "commands": [f"npm install {module_name}"],
                    "reasoning": f"Module '{module_name}' not found. Installing it.",
                }

        # ENOENT — file not found (usually missing package.json)
        if "ENOENT" in stderr and "package.json" in stderr:
            return {
                "action": "configure",
                "commands": ["npm init -y"],
                "reasoning": "No package.json found. Initializing project.",
            }

        return None

    def handle_error(self, stderr: str, context: dict[str, Any]) -> dict[str, Any]:
        result = self.diagnose(stderr, context)
        if result:
            result["method"] = "introspection"
            return result

        pattern = self.match_error_pattern(stderr)
        if pattern:
            pattern["method"] = "knowledge_base"
            return pattern

        return {
            "diagnosed": False,
            "method": "unknown",
            "suggestions": [
                "Try deleting node_modules and running npm install again",
                "Check Node.js version compatibility",
            ],
        }

    # ── Private ─────────────────────────────────────────────────

    def _parse_packages_from_description(self, description: str) -> list[str]:
        known_packages = {
            "react", "next", "nextjs", "vue", "angular", "svelte",
            "express", "fastify", "koa", "nestjs", "hapi",
            "typescript", "ts-node", "tsx",
            "eslint", "prettier", "jest", "vitest", "mocha",
            "webpack", "vite", "rollup", "esbuild", "turbo",
            "tailwindcss", "sass", "less",
            "axios", "node-fetch", "got",
            "mongoose", "prisma", "sequelize", "typeorm",
            "nodemon", "pm2", "dotenv",
            "socket.io", "ws",
            "zod", "joi", "yup",
        }

        words = re.findall(r'[\w.-]+', description.lower())
        found = []
        for word in words:
            if word in known_packages:
                found.append(word)
            elif word == "nextjs":
                found.append("next")

        return found if found else []
