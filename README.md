# Shellock
Adaptive Terminal Environment Orchestrator

## Quick Start

```bash
# cd into the project
cd shellock

# Install in dev mode
pip install -e ".[dev]"

# Verify it works
shellock --help
shellock version
shellock modules
```

## Testing

```bash
# Run all tests (from the shellock/ project root)
pytest tests/ -v

# Run only core tests (schemas, dispatcher, fingerprinting)
pytest tests/test_core.py -v

# Run only module tests (Python + Node interface proof)
pytest tests/test_modules.py -v

# Run a specific test
pytest tests/test_modules.py::TestPythonModule::test_diagnose_module_not_found -v
```

## Try It Out

```bash
# Init an environment (will trigger onboarding on first run)
shellock init "python 3.11 fastapi project with black"

# List project history
shellock list

# Diagnose an error
shellock fix "ModuleNotFoundError: No module named 'fastapi'"

# See available modules
shellock modules

# View/set config
shellock config
shellock config llm_provider ollama

# Inspect the Shellock profile
shellock profile  # shows system/hardware info plus the active spec

# Dry run (shows what would happen, no execution)
shellock init "node react app with typescript" --dry-run

# Rollback the last action
shellock rollback
```

## Cleanup

```bash
# Delete a specific environment
rm -rf ~/.shellock/envs/py-python-3-11

# Delete all Shellock environments
rm -rf ~/.shellock/envs/

# Delete a project's Shellock history
rm -rf .shellock/

# Full reset (removes all Shellock data — profile, config, envs, history)
rm -rf ~/.shellock/
```

## Uninstall

To completely remove Shellock from your system:

```bash
# 1. Uninstall the package (removes the `shellock` CLI command)
pip uninstall shellock

# 2. Remove all Shellock global data (profile, config, envs, history)
rm -rf ~/.shellock/

# 3. Remove local project data (if inside a project that used shellock)
rm -rf .shellock/
```

After these steps, `shellock` will no longer be available as a command and all stored environments, config, and history will be gone.

## Project Structure

```
shellock/                   # project root (git repo)
├── pyproject.toml          # packaging, CLI entry point, module entry points
├── tests/
│   ├── test_core.py        # 16 tests — schemas, dispatcher, fingerprinting
│   └── test_modules.py     # 21 tests — both modules + interface proof
└── shellock_core/          # package source
    ├── cli.py              # CLI entry point (Typer)
    ├── module_base.py      # ShellockModule ABC — the interface all modules implement
    ├── core/
    │   ├── schemas.py      # Pydantic models (EnvSpec, Profile, History)
    │   ├── context.py      # OS/project/LLM detection
    │   ├── llm.py          # Ollama + litellm interface
    │   ├── dispatcher.py   # Command validation + execution
    │   ├── registry.py     # Audit trail + file locking
    │   ├── ui.py           # Rich terminal UI + plain fallback
    │   ├── module_loader.py# Module discovery
    │   └── onboarding.py   # First-run wizard
    └── modules/
        ├── python/         # Python ecosystem module
        │   ├── module.py
        │   └── knowledge/errors.json
        └── node/           # Node ecosystem module
            ├── module.py
            └── knowledge/errors.json
```

## Environment Variables

| Variable | Effect |
|---|---|
| `SHELLOCK_PLAIN=1` | Disable Rich formatting (plain text output) |
