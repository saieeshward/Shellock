# Shellock — Team Handoff Document

**Project:** Shellock — Adaptive Terminal Environment Orchestrator
**Course:** CS7IS5 — Adaptive Applications (Trinity College Dublin)
**Version:** 0.1.0
**Date:** March 2026
**Status:** Working baseline — 37/37 tests passing, end-to-end demo verified

---

## 1. What Is Shellock?

Shellock is a **human-gated Large Action Model (LAM)** for developer environment setup and error diagnosis. It watches what you do in the terminal, understands your intent, proposes actions, and executes them — but **only after you approve**.

The adaptive loop:

```
Perceive → Plan → Human Approve → Execute → Observe → Adapt
```

Think of it as an intelligent assistant that sits between you and your terminal, handling the grunt work of setting up Python venvs, installing packages, diagnosing `ModuleNotFoundError`, and learning your preferences over time — without ever doing anything behind your back.

---

## 2. The Three Pillars

### Pillar 1: Adaptability
- Learns user preferences via deterministic frequency counters (not ML)
- After you pick `black` as your formatter 3+ times, Shellock auto-suggests it
- Four-layer error resolution escalates from fast/offline to smart/slower
- System introspection uses Python's own `importlib.metadata` for instant, accurate diagnosis

### Pillar 2: Scrutability ("No Black Box")
- The LLM only does text → JSON conversion. It never executes commands
- Every action is validated against allowlists before execution
- Full audit trail with causal linking (did fix A cause error B?)
- User can inspect, edit, and explain every spec before it runs
- Error fingerprinting creates stable hashes for pattern tracking

### Pillar 3: Universal Compatibility
- Works offline (Ollama local LLM) or online (cloud LLM) or without any LLM (template fallback)
- Modular architecture — Python and Node built-in, anyone can add more
- Rich terminal UI with `SHELLOCK_PLAIN=1` fallback for constrained environments
- macOS, Linux, Windows support via standard Python tooling

---

## 3. Architecture Questions & Agreed Answers

These are the 15+ design questions raised during planning, and the decisions we settled on.

### Q1: How does Shellock adapt without feeling creepy?

**Answer:** Deterministic preference counters, not ML profiling. Shellock tracks `{"formatter": {"black": 5, "ruff": 1}}` — pure frequency counts. After `suggestion_threshold` uses (default 3), it auto-suggests. Users can reject suggestions, and rejected items are never re-suggested. No telemetry, no cloud sync, no hidden state.

### Q2: How is privacy handled?

**Answer:** Everything stays local by default. Profile in `~/.shellock/profile.json`, project history in `<project>/.shellock/history.json`. The LLM runs locally via Ollama. Cloud LLM is opt-in only and requires explicit API key configuration. No data leaves the machine unless the user configures it.

### Q3: What user model does Shellock use?

**Answer:** `UserProfile` (Pydantic model) with:
- `preferences: dict[str, dict[str, int]]` — category → {tool: count}
- `suggestion_threshold: int` — minimum uses before auto-suggesting
- `rejected_suggestions: list[str]` — never suggest these again
- `system: SystemInfo` — detected OS, arch, shell, package managers, LLM tier

This is a **deterministic model**, not a probabilistic one. No embeddings, no vectors, no ML.

### Q4: Won't Rich be slow on low-spec machines?

**Answer:** `SHELLOCK_PLAIN=1` disables Rich entirely. Every UI function has a `_plain_*()` fallback that uses standard `print()` and `input()`. Rich is imported lazily (inside functions, not at module level) so it doesn't affect startup time if disabled.

### Q5: How does Shellock work across OS/shell combinations?

**Answer:** `context.py` detects OS (`platform.system()`), shell (`$SHELL` or `$COMSPEC`), architecture (`platform.machine()`), and available package managers (`shutil.which()`). All detection is deterministic — no guessing. The dispatcher handles path separators and command differences. Modules generate OS-appropriate commands.

### Q6: What happens on first run? How fast is onboarding?

**Answer:** ~30 seconds, 3-5 questions, one-time only. Three phases:
1. **Auto-detect** (no user input) — OS, shell, LLM availability, installed tools
2. **Module questions** — each module asks 1-2 preferences (e.g., "Preferred formatter?")
3. **LLM preference** — use detected Ollama? Configure cloud? Template-only?

Sets `onboarding_complete: true` in profile so it never runs again.

### Q7: What if there's no LLM and no internet?

**Answer:** Three-tier fallback:
1. **Local LLM** (Ollama on port 11434) — private, offline, low latency
2. **Cloud LLM** (litellm) — requires API key + internet
3. **Template fallback** — module's `build_spec()` uses keyword matching against 90+ known packages. No AI needed. Still works, just less smart.

For error diagnosis, the same principle: introspection → knowledge base patterns → LLM → "I don't know".

### Q8: Does Shellock ever say "I don't know"?

**Answer:** Yes. Layer 4 of error resolution is an explicit "I don't know" with:
- Suggestions for the user to try
- Stack Overflow search link
- Resource links from the knowledge base
- No hallucinated fixes. Honesty > confidence.

### Q9: How does Shellock understand project context?

**Answer:** `context.py:detect_project_context()` scans for indicator files:
- Python: `requirements.txt`, `pyproject.toml`, `Pipfile`, `setup.py`
- Node: `package.json`, `.nvmrc`, `yarn.lock`
- Docker: `Dockerfile`, `docker-compose.yml`
- Also: Rust (`Cargo.toml`), Go (`go.mod`), Ruby (`Gemfile`)

Plus checks for existing venvs (`.venv/`, `venv/`) and existing Shellock config (`.shellock/`).

### Q10: Can Shellock read project files to understand them?

**Answer:** Yes, but only specific files:
- `requirements.txt` → list of Python dependencies
- `package.json` → name, dependencies, devDependencies
- `pyproject.toml` → presence check (not full parsing yet)

It does NOT read arbitrary source code. This is intentional — Shellock manages environments, not code.

### Q11: How are JSON files updated safely?

**Answer:** `registry.py` uses `fcntl.flock()` for file-level locking. Writes are atomic: lock → read → modify → write → unlock. Retries every 0.1s for up to 5 seconds if another process holds the lock. History compaction kicks in after 200 actions to keep files small.

### Q12: What about RAM/storage impact?

**Answer:** Minimal. Profile and config are <1KB each. History grows with usage but is compacted at 200 entries (keeps last 100, archives older). Module caching prevents re-instantiation. Pydantic models are lightweight. Ollama runs as a separate process with its own memory management.

### Q13: How are LLM context limits handled?

**Answer:** `LLMClient` only sends the last 5 recent actions to the LLM (not full history). Prompts are structured with clear JSON schemas. The LLM does text → JSON only — it doesn't need to understand the full project. Max 3 retries with validation feedback if output isn't valid JSON.

### Q14: How is command execution made safe?

**Answer:** Multi-layer safety:
1. **Allowlist** — each module defines allowed command prefixes (e.g., `["pip install", "python -m venv"]`)
2. **Blocked patterns** — regex reject list (e.g., `r"sudo\s+"`, `r"rm\s+-rf"`, `r"pip\s+install\s+--break-system-packages"`)
3. **Impact classification** — SAFE (green), CAUTION (yellow), BLOCKED (red)
4. **Two approval gates** — spec approval + command approval
5. **Basename normalization** — `/Users/.../bin/pip install` still matches `pip install`
6. **Venv isolation** — packages always install into isolated environments, never system Python

### Q15: Can we use Python's own introspection (help(), importlib.metadata)?

**Answer:** Yes, this is Layer 1 of error resolution and the most powerful feature. `PythonModule.introspect()` uses:
- `importlib.metadata.distributions()` — list ALL installed packages with versions
- `importlib.metadata.version(name)` — check if a specific package is installed
- `sys.version_info` — current Python version
- `sysconfig.get_path("purelib")` — site-packages location
- `sys.prefix != sys.base_prefix` — detect if inside a venv
- `difflib.get_close_matches()` — "did you mean?" suggestions

This is **instant, 100% accurate, works offline**, and runs before any LLM call.

---

## 4. System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     CLI Layer (cli.py)                   │
│  init │ fix │ list │ envs │ use │ rollback │ modules │  │
└───────┬────────────────────────────────────┬────────────┘
        │                                    │
        ▼                                    ▼
┌───────────────┐                  ┌──────────────────┐
│   UI Layer    │                  │  Module Loader   │
│   (ui.py)     │                  │ (module_loader)  │
│ Rich + Plain  │                  │ Built-in + Entry │
└───────────────┘                  │    Points        │
                                   └────────┬─────────┘
                                            │
        ┌───────────────────────────────────┼──────────┐
        │                                   │          │
        ▼                                   ▼          ▼
┌───────────────┐               ┌──────────────┐ ┌──────────┐
│    Context    │               │    Python    │ │   Node   │
│  (context.py) │               │   Module     │ │  Module  │
│ OS/Shell/LLM  │               │ (399 lines)  │ │(311 lines│
│  detection    │               └──────┬───────┘ └────┬─────┘
└───────────────┘                      │              │
                                       ▼              ▼
                              ┌──────────────────────────┐
                              │   ShellockModule ABC     │
                              │   (module_base.py)       │
                              │ 8 abstract methods       │
                              │ 2 concrete helpers       │
                              └──────────────────────────┘

┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   Dispatcher    │  │     Registry     │  │   LLM Client     │
│ (dispatcher.py) │  │  (registry.py)   │  │    (llm.py)      │
│ Validate + Exec │  │ Audit + Profile  │  │ Ollama/litellm   │
│ Allowlist check │  │ File locking     │  │ Retry + Validate │
│ Subprocess.run  │  │ Fingerprinting   │  │ JSON extraction  │
└─────────────────┘  └──────────────────┘  └──────────────────┘
```

---

## 5. The Module Interface

Every ecosystem module implements `ShellockModule` (ABC). This is the extensibility contract:

```python
class ShellockModule(ABC):
    # Class attributes
    name: str                    # "python", "node"
    description: str             # One-line for CLI listing
    triggers: list[str]          # Files that activate this module
    allowed_commands: list[str]  # Command prefix allowlist
    blocked_patterns: list[str]  # Regex deny list
    suggestable_tools: list[str] # Tools to auto-suggest after N uses

    # Abstract methods — MUST implement
    def detect(project_path) -> bool           # Does this module apply?
    def onboarding_questions() -> list[dict]   # First-run questions
    def introspect(project_path) -> dict       # System state snapshot
    def build_spec(description, context) -> dict  # NL → env spec (no LLM)
    def validate_spec(spec) -> list[dict]      # Cross-check vs reality
    def dispatch(spec) -> list[dict]           # Spec → shell commands
    def diagnose(stderr, context) -> dict|None # Introspection-only fix
    def handle_error(stderr, context) -> dict  # Full resolution chain

    # Concrete (inherited)
    def load_error_patterns() -> list[dict]    # Load knowledge/errors.json
    def match_error_pattern(stderr) -> dict|None  # Regex match
```

**To add a new module (e.g., Rust):**
1. Create `shellock_core/modules/rust/module.py` implementing the ABC
2. Add `shellock_core/modules/rust/knowledge/errors.json`
3. Register in `pyproject.toml` entry points
4. Zero changes to core code

---

## 6. Four-Layer Error Resolution

```
Error arrives ("ModuleNotFoundError: No module named 'fastapi'")
    │
    ▼
Layer 1: INTROSPECTION (instant, offline, 100% accurate)
    │  module.diagnose() → uses importlib.metadata, sys, difflib
    │  Result: "fastapi is not installed. pip install fastapi"
    │  ✓ Done? → Show fix, ask to apply
    │
    ▼ (if Layer 1 fails)
Layer 2: KNOWLEDGE BASE (fast, offline)
    │  module.match_error_pattern() → regex against errors.json
    │  10 Python patterns, 8 Node patterns
    │  ✓ Done? → Show fix
    │
    ▼ (if Layer 2 fails)
Layer 3: LLM (smart, slower, may hallucinate)
    │  llm.diagnose_error() → Ollama/litellm with context
    │  Includes system info + last 5 actions
    │  ✓ Done? → Show fix (with yellow "via LLM" badge)
    │
    ▼ (if Layer 3 fails)
Layer 4: "I DON'T KNOW" (honest)
    │  Suggestions + Stack Overflow link + docs links
    │  No hallucinated fixes
    └─ Done
```

---

## 7. Data Flow: `shellock init`

```
User: shellock init "python 3.11 fastapi project with black" --name my-api
    │
    ├─ 1. Check onboarding (first run only)
    │
    ├─ 2. Detect module
    │     └─ Scan project files → PythonModule.detect()
    │     └─ No files? Infer from description → default to python
    │
    ├─ 3. Gather context (NO LLM)
    │     ├─ System: OS, arch, shell, package managers, LLM tier
    │     ├─ Project: existing files, venvs, .shellock config
    │     └─ Introspection: installed packages, Python versions
    │
    ├─ 4. Generate spec
    │     ├─ LLM available? → llm.generate_spec() with SPEC_PROMPT
    │     └─ No LLM? → module.build_spec() (keyword matching)
    │     └─ --name flag? → override env_id with user's name
    │
    ├─ 5. Validate spec
    │     └─ module.validate_spec() → warnings ("numpy already installed")
    │
    ├─ 6. Approval gate #1: Show spec
    │     ├─ env_id, module, runtime, packages, env_path
    │     ├─ Warnings from validation
    │     ├─ LLM reasoning
    │     └─ User: yes / no / edit / explain
    │     └─ (skipped with --yes flag)
    │
    ├─ 7. Generate commands
    │     └─ module.dispatch() → [venv create, pip upgrade, pip install]
    │
    ├─ 8. Validate commands
    │     └─ dispatcher.validate_commands() → allowlist + blocked check
    │
    ├─ 9. Approval gate #2: Show commands
    │     ├─ Green (SAFE) / Yellow (CAUTION) / Red (BLOCKED)
    │     └─ User approves safe and/or cautioned commands
    │     └─ (skipped with --yes flag)
    │
    ├─ 10. Execute
    │      └─ dispatcher.execute_commands() → subprocess, sequential
    │
    ├─ 11. Record audit trail
    │      └─ registry.record_action(type=INIT, spec, commands, result)
    │
    ├─ 12. Update preferences
    │      └─ profile.record_choice("tools", "black") etc.
    │
    └─ 13. Show activation hint
           └─ "source ~/.shellock/envs/my-api/bin/activate"
```

### Full Environment Workflow

```
shellock init "python ML project" --name ml-env    # Create & name
shellock envs                                       # List all environments
shellock use ml-env                                 # Activate (spawns subshell)
# ... work in the environment ...
exit                                                # Deactivate & return to normal shell
```

---

## 8. File Storage Layout

```
~/.shellock/                    # Global (per-user)
├── profile.json                # UserProfile — preferences, system info
├── config.json                 # ShelllockConfig — LLM provider, model
└── envs/                       # Created environments
    ├── py-python-3-11/         # A Python venv
    └── ml-env/                 # Another Python venv

<any-project>/.shellock/        # Per-project
├── spec.json                   # Current active EnvSpec
├── history.json                # Action audit trail
└── history.archive.json        # Compacted old entries (>200 actions)
```

---

## 9. Project Structure

```
shellock/                       # Project root
├── pyproject.toml              # Packaging, CLI entry point, module entry points
├── TEAM_HANDOFF.md             # This document
├── README.md                   # Quick start + testing guide
├── .gitignore
├── tests/
│   ├── test_core.py            # 16 tests — schemas, dispatcher, fingerprinting
│   └── test_modules.py         # 21 tests — both modules + interface proof
└── shellock_core/              # Package source
    ├── __init__.py             # Version export
    ├── cli.py                  # Typer CLI (553 lines)
    ├── module_base.py          # ShellockModule ABC (203 lines)
    ├── core/
    │   ├── schemas.py          # Pydantic models (248 lines)
    │   ├── context.py          # System/project detection (187 lines)
    │   ├── llm.py              # Ollama + litellm interface (265 lines)
    │   ├── dispatcher.py       # Command validation + execution (221 lines)
    │   ├── registry.py         # Audit trail + file locking (306 lines)
    │   ├── ui.py               # Rich terminal UI + plain fallback (413 lines)
    │   ├── module_loader.py    # Module discovery (112 lines)
    │   └── onboarding.py       # First-run wizard (136 lines)
    └── modules/
        ├── python/
        │   ├── module.py       # Python module (399 lines)
        │   └── knowledge/
        │       └── errors.json # 10 error patterns
        └── node/
            ├── module.py       # Node module (311 lines)
            └── knowledge/
                └── errors.json # 8 error patterns
```

**Total:** ~3,670 lines of code across 14 source files + 2 test files.

---

## 10. Key Dependencies

| Package | Purpose | Required? |
|---------|---------|-----------|
| `typer>=0.9.0` | CLI framework | Yes |
| `rich>=13.0.0` | Terminal UI (tables, panels, colors) | Yes |
| `pydantic>=2.0.0` | Data validation, schema enforcement | Yes |
| `ollama>=0.3.0` | Local LLM client (Ollama API) | Yes |
| `litellm` | Cloud LLM support (OpenAI, etc.) | Optional (`pip install shellock[cloud]`) |
| `pytest` | Testing | Dev only (`pip install shellock[dev]`) |

---

## 11. How to Run & Test

```bash
# Install in dev mode
cd shellock
pip install -e ".[dev]"

# Verify
shellock --help
shellock version
shellock modules

# Run all 37 tests
pytest tests/ -v

# Try it out (with Ollama running)
shellock init "python 3.11 fastapi project with black"

# Name the environment explicitly
shellock init "python ML project with numpy pandas" --name ml-env

# Auto-approve (no prompts)
shellock init "python 3.11 data science with pandas numpy" --yes --name ds-env

# Dry run (preview only)
shellock init "node react app with typescript" --dry-run

# List all environments
shellock envs

# View env details + activation command
shellock use ml-env

# Diagnose an error
shellock fix "ModuleNotFoundError: No module named 'fastapi'"

# View project action history (timeline format)
shellock list

# Configure LLM
shellock config llm_model llama3.2:3b
```

---

## 12. What's Built vs. What's Next

### Done (current baseline)

- [x] ShellockModule ABC with 8 abstract methods
- [x] Python module — full venv lifecycle, introspection, 10 error patterns
- [x] Node module — npm lifecycle, introspection, 8 error patterns
- [x] CLI with 9 commands (init, fix, list, envs, use, rollback, modules, config, version)
- [x] Ollama integration (local LLM, tested with llama3.2:3b)
- [x] litellm integration (cloud LLM, code ready)
- [x] Template fallback (no LLM mode, keyword matching)
- [x] Four-layer error resolution chain
- [x] Deterministic user preference learning
- [x] Full audit trail with error fingerprinting
- [x] Cascading error detection
- [x] Rich terminal UI + plain-text fallback
- [x] First-run onboarding wizard
- [x] Command safety (allowlist, blocked patterns, two-gate approval)
- [x] `--yes` / `-y` flag for automated/scripted usage (skips both approval gates)
- [x] `--name` / `-n` flag for explicit environment naming
- [x] `--dry-run` flag for preview
- [x] `shellock envs` — list all environments with Python version, packages, and activation command
- [x] `shellock use <name>` — show environment details and activation hint
- [x] Post-init activation hint (shows how to activate the newly created env)
- [x] File locking for concurrent access
- [x] History compaction
- [x] 37 tests passing

### Potential Next Steps

### `shellock list` — Timeline Format

The `shellock list` command shows project history in a compact timeline:

```
++ INIT  ml-env  OK  2026-03-02 19:10  (act-5df7ca)
   numpy, pandas, scikit-learn
   ~/.shellock/envs/ml-env
```

Each entry shows: action type, env name, result, timestamp, and action ID, with packages and path on subsequent lines.

### Potential Next Steps

- [ ] `shellock add "package"` — add packages to an existing environment
- [ ] `shellock remove "package"` — remove with dependency cleanup
- [ ] Automatic rollback (reverse commands, not just record)
- [ ] Docker module
- [ ] Rust module
- [ ] VS Code extension
- [ ] Template hub (community-shared environment templates)
- [ ] Pipe support (`command 2>&1 | shellock fix`)
- [ ] Shell integration (auto-detect last error from shell history)
- [ ] Binary distribution (standalone executable, no Python required)

---

## 13. How the LAM Classification Works

Shellock qualifies as a **Large Action Model** because it:

1. **Perceives** — detects OS, shell, installed tools, project files, LLM availability
2. **Plans** — LLM converts natural language to structured environment spec
3. **Validates** — Pydantic schemas + allowlist + blocked patterns
4. **Requires human approval** — two gates (spec + commands)
5. **Acts** — executes approved commands via subprocess
6. **Observes** — captures stdout/stderr, records in audit trail
7. **Adapts** — preference learning, error frequency tracking, cascading fix detection

The key differentiator: **human-gated**. The LLM proposes, the human disposes. This makes it safe, scrutable, and trustworthy — critical for a tool that modifies your system.

---

## 14. Quick Reference: All Pydantic Models

| Model | File | Purpose |
|-------|------|---------|
| `PackageSpec` | schemas.py | Single package (name, version, extras) |
| `EnvSpec` | schemas.py | Environment specification (the core entity) |
| `Command` | schemas.py | Shell command with impact + rollback |
| `ActionEntry` | schemas.py | Audit trail entry |
| `ProjectHistory` | schemas.py | Per-project action history |
| `SystemInfo` | schemas.py | Detected system capabilities |
| `UserProfile` | schemas.py | Global user preferences |
| `DiagnosisResult` | schemas.py | Error diagnosis output |
| `ShelllockConfig` | schemas.py | Global configuration |

All models have `extra='forbid'` — any unexpected field from LLM output is caught immediately.

---

## 15. Quick Reference: All CLI Commands

| Command | Description | Key Flags |
|---------|-------------|-----------|
| `shellock init "desc"` | Create environment from description | `--module`, `--template`, `--dry-run`, `--yes`/`-y`, `--name`/`-n` |
| `shellock fix "error"` | Diagnose and fix an error | |
| `shellock list` | Show project action history (timeline format) | |
| `shellock envs` | List all environments with versions & packages | |
| `shellock use <name>` | Activate environment (spawns subshell) | |
| `shellock rollback [id]` | Undo a previous action | |
| `shellock modules` | List available modules | |
| `shellock config [key] [val]` | View/set configuration | |
| `shellock profile` | Show tracked preferences, recent errors, and detected hardware/spec info | |
| `shellock version` | Show version | |

### Environment Lifecycle

```bash
# Create with explicit name
shellock init "python data science project" --name ds-env --yes

# List all environments
shellock envs
# ┌──────────┬─────────┬──────────────────────────────┬──────────────────────────────────────────┐
# │ Name     │ Python  │ Packages                     │ Activate                                 │
# ├──────────┼─────────┼──────────────────────────────┼──────────────────────────────────────────┤
# │ ds-env   │ 3.11.8  │ numpy, pandas, scikit-learn   │ source ~/.shellock/envs/ds-env/bin/activate │
# │ ml-env   │ 3.12.1  │ torch, transformers            │ source ~/.shellock/envs/ml-env/bin/activate │
# └──────────┴─────────┴──────────────────────────────┴──────────────────────────────────────────┘

# Activate an environment (spawns a subshell)
shellock use ds-env

# Deactivate — just exit the subshell
exit
```
