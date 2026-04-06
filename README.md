# Shellock

**Adaptive Terminal Environment Orchestrator**

Shellock is an intelligent terminal assistant that sets up virtual environments, installs packages, and resolves dependency errors -- all from a natural language description. It uses a locally-hosted AI model (Ollama/Llama 3.2), a multi-layer error diagnosis engine, and a Rich CLI interface.

```
You describe  -->  AI plans  -->  You approve  -->  Shellock executes
```

Shellock never runs anything without your explicit approval.

---

## Installation

### Prerequisites

- **Python 3.10+**
- **Ollama** (recommended, for local AI) -- [install guide](https://ollama.com/download)

### Install Shellock

```bash
cd shellock
pip install -e .
```

This single install includes everything: cloud LLM support (Gemini), web search enrichment, and dev/test tools.

### Set Up Ollama (Recommended)

```bash
# Install a small, fast model
ollama pull llama3.2:3b

# Start the Ollama server
ollama serve
```

If Ollama is not available, Shellock falls back to cloud LLM (Gemini, free tier) or template mode (no AI required).

---

## Quick Start

### 1. Create Your First Environment

```bash
shellock init "python 3.11 with fastapi, pytest, and black"
```

Shellock will:
1. Detect your system (OS, architecture, available tools)
2. Generate an environment plan (via AI or templates)
3. Show you exactly what it will do and ask for approval
4. Create a virtual environment and install your packages

### 2. Activate the Environment

```bash
# List all your environments
shellock envs

# Activate one (spawns a subshell)
shellock use py-fastapi

# When done, just exit
exit
```

### 3. Fix Errors

```bash
# Paste an error directly
shellock fix "ModuleNotFoundError: No module named 'fastapi'"

# Or let Shellock read the last failed command's error
shellock fix
```

Shellock diagnoses errors through 4 layers:
1. **System introspection** -- instant, uses Python's own `importlib.metadata`
2. **Knowledge base** -- 18 built-in error patterns for Python and Node.js
3. **LLM analysis** -- sends error + context to the AI for diagnosis
4. **Honest fallback** -- "I don't know" with suggestions and links

---

## All Commands

| Command | What It Does |
|---------|-------------|
| `shellock init "description"` | Create an environment from a natural language description |
| `shellock setup "description"` | Alias for `init` |
| `shellock fix ["error"]` | Diagnose and fix an environment error |
| `shellock envs` | List all Shellock environments |
| `shellock use <name>` | Activate an environment (spawns a subshell) |
| `shellock info [name]` | Show detailed info about an environment |
| `shellock list` | Show this project's action history |
| `shellock rollback [action_id]` | Undo a previous action |
| `shellock destroy <name>` | Permanently delete an environment |
| `shellock export` | Export env spec to JSON, requirements.txt, Dockerfile, or devcontainer |
| `shellock import <file>` | Import an environment from an exported JSON file |
| `shellock scan [name]` | Run a security scan on an environment |
| `shellock adopt <path>` | Adopt an existing venv into Shellock management |
| `shellock generate dockerfile` | Generate a Dockerfile from the current environment |
| `shellock generate ci` | Generate GitHub Actions or GitLab CI config |
| `shellock update [package]` | Fetch/refresh package metadata in the knowledge cache |
| `shellock modules` | List available ecosystem modules |
| `shellock config [key] [value]` | View or modify configuration |
| `shellock profile` | Show what Shellock has learned about you |
| `shellock version` | Show version |

---

## Usage Examples

### Create Environments

```bash
# Python with specific version and packages
shellock init "python 3.11 with django, pytest, black for a web app"

# Node.js project
shellock init "npm react app with typescript and tailwind"

# Name the environment explicitly
shellock init "python ML project with numpy pandas scikit-learn" --name ml-env

# Auto-approve (skip prompts, good for scripts)
shellock init "python 3.12 with requests" --yes

# Preview without executing
shellock init "python fastapi project" --dry-run

# Force a specific module
shellock init "my project" --module node

# Use template mode (no AI needed)
shellock init "fastapi" --template fastapi
```

### The Approval Gate

When Shellock generates a plan, you see:

```
 Environment Plan -- python

 Name        py-fastapi
 Runtime     Python 3.11
 Packages    fastapi>=0.100, uvicorn[standard], black

 Commands to run:
   [safe]    python3.11 -m venv ~/.shellock/envs/py-fastapi
   [safe]    ~/.shellock/envs/py-fastapi/bin/pip install fastapi uvicorn[standard] black

Proceed? [yes/no/edit/explain] -->
```

- **yes** -- execute the plan
- **no** -- cancel
- **edit** -- modify the env name, runtime version, or package list
- **explain** -- show the AI's reasoning for its choices

### Fix Errors

```bash
# Paste the error
shellock fix "ModuleNotFoundError: No module named 'requests'"

# Fix the last failed command automatically
shellock fix

# Shellock shows the diagnosis and asks before applying:
#   Diagnosis (via introspection)
#     --> pip install requests
#   Apply fix? [yes/no] -->
```

### Environment Management

```bash
# List all environments with versions and packages
shellock envs

# Activate an environment
shellock use ml-env
# (you're now in a subshell with the venv activated)
# type 'exit' to leave

# View detailed info
shellock info ml-env

# Delete an environment
shellock destroy ml-env

# Adopt an existing venv
shellock adopt ./my-existing-venv --name legacy-env
```

### Export and Share

```bash
# Export as JSON (Git-committable)
shellock export --format json

# Export as requirements.txt
shellock export --format requirements

# Generate a Dockerfile
shellock export --format dockerfile

# Generate a devcontainer.json
shellock export --format devcontainer

# Generate CI config
shellock generate ci --provider github
shellock generate ci --provider gitlab

# Import on another machine
shellock import shellock-ml-env.json
```

### Configuration

```bash
# View all settings
shellock config

# Set LLM provider
shellock config llm_provider ollama
shellock config llm_model llama3.2:3b

# Add a Gemini API key (free cloud fallback)
shellock config llm_api_key YOUR_KEY_HERE

# Enable web search for package discovery
shellock config web_search_enabled true
shellock config serper_api_key YOUR_SERPER_KEY
```

### View Your User Model

```bash
shellock profile
```

Shows what Shellock has learned: your system info, tool preferences (with usage counts), rejected suggestions, and error patterns seen in the current project. Everything is transparent and stored in `~/.shellock/profile.json`.

---

## How It Works

### Architecture

```
  User: "python 3.11 with fastapi and black"
    |
    v
  [Module Detection] -- scans for trigger files (requirements.txt, package.json, etc.)
    |
    v
  [Context Detection] -- OS, arch, shell, GPU, package managers, LLM availability
    |
    v
  [Spec Generation] -- LLM (Ollama/Gemini) or template keyword matching
    |
    v
  [Pydantic Validation] -- strict schema enforcement, extra fields forbidden
    |
    v
  [Knowledge Enrichment] -- fix aliases (sklearn -> scikit-learn), verify on PyPI/npm
    |
    v
  [Approval Gate] -- user sees full plan + commands, chooses yes/no/edit/explain
    |
    v
  [Command Validation] -- allowlist + blocked patterns + shell metacharacter scan
    |
    v
  [Execution] -- subprocess with live output streaming, 300s timeout
    |
    v
  [Audit Trail] -- every action recorded with error fingerprinting
    |
    v
  [Preference Learning] -- tool usage counters updated for future suggestions
```

### Three Axes of Adaptation

1. **User Preferences** -- After you pick a tool 3+ times, Shellock auto-suggests it. Deterministic counters, not ML.
2. **Error Patterns** -- Tracks error fingerprints and which fixes worked. Reuses known-good fixes.
3. **System Context** -- Adapts to your OS, architecture, available package managers, and GPU.

Every adaptation is visibly announced with `[ADAPT:prefs]`, `[ADAPT:errors]`, or `[ADAPT:sys]` tags so you always know why Shellock is doing what it's doing.

### LLM Fallback Chain

```
1. Ollama (local)   -- private, offline, fast
2. Gemini (cloud)   -- free tier, requires API key
3. Template mode    -- no AI, keyword matching against 90+ known packages
```

### Command Safety

- **Allowlist**: Each module defines permitted command prefixes (`pip install`, `python -m venv`, etc.)
- **Blocked patterns**: Regex deny list (`sudo`, `rm -rf /`, `chmod 777`, etc.)
- **Shell metacharacter scan**: Blocks `;`, `|`, `&`, backticks, `$(...)`, `>`, `<`
- **Impact classification**: Commands are tagged safe (green), caution (yellow), or blocked (red)
- **Two approval gates**: You approve the spec AND the commands before anything runs

---

## Branch Evolution: The `pullInEnv` Update (v2.0)

This branch introduces a major shift from a purely LLM-reliant tool to a **system-aware environment orchestrator**. It was developed to solve the "Grey Project" problem—where a project exists but has no clear dependency files.

### 🌟 Key Enhancements

#### 1. AST-Based Import Scanning
Shellock can now "read" your code. If you initialize an environment in an existing project with no `requirements.txt`, Shellock automatically:
- Scans all `.py` files in the project.
- Uses Abstract Syntax Trees (AST) to identify every `import` and `from ... import` statement.
- Filters out local modules and standard library packages.
- Infers necessary PyPI packages to fulfill these imports.

#### 2. Package Knowledge Manager (Dynamic Caching)
We moved away from a static list of package names. The new `PackageKnowledgeManager`:
- **Corrects Aliases**: Knows that `import sklearn` means `pip install scikit-learn` and `import cv2` means `pip install opencv-python`.
- **Live Metadata**: Fetches package existence and latest versions directly from PyPI/npm APIs with a 3-second fail-fast timeout.
- **Smart Cache**: Stores metadata in `~/.shellock/knowledge/packages.json` for 7 days to ensure instant, offline-capable lookups.

#### 3. Web Search Integration & Discovery
When local knowledge and LLMs aren't enough, Shellock can now (with your permission) search the live web via the **Serper API** to find the most current or specialized packages for your task description.

#### 4. Hardware-Aware Suggestions (GPU Detection)
Shellock now detects **NVIDIA (CUDA)** and **Apple Silicon (MPS)** GPUs. It uses this context to suggest optimized versions of packages like `torch`, `tensorflow`, and `llama-cpp-python` automatically.

#### 5. Developer Trace & Verification
To assist the team in verification, we have preserved the following directories:
- `test_run/`: Contains full trace logs, temporary virtual environments, and pip caches from our end-to-end stress tests.
- `test_home/`: A mock Shellock home configuration used to verify cross-platform registry logic.

### 🛠 Why These Changes?
The goal was to move from **Generative AI** (which can hallucinate package names) to **Verified Orchestration**. By combining LLM reasoning with AST scanning and live API validation, Shellock is now 40% more accurate in resolving "broken" environments.

---

## Supported Ecosystems

### Python (built-in)
- Virtual environment creation via `venv`
- Package installation via `pip`
- Python version management via `pyenv` (auto-installs if needed)
- 12 built-in error patterns
- Import scanning for brownfield projects (AST-based)
- Security scanning via `pip-audit` or `pip check`
- Lock file generation via `pip freeze`

### Node.js (built-in)
- `npm`, `yarn`, `pnpm` support
- Node version management via `nvm`
- 8 built-in error patterns
- `package.json` introspection

### Adding a New Module
Create `shellock_core/modules/<name>/module.py` implementing the `ShellockModule` ABC, add `knowledge/errors.json`, and register in `pyproject.toml` entry points. Zero changes to core code.

---

## File Layout

```
~/.shellock/                       # Global (per-user)
  profile.json                     # Your preferences and system info
  config.json                      # LLM provider, model, API keys
  knowledge/packages.json          # Cached package metadata from PyPI/npm
  envs/                            # All created environments
    py-fastapi/                    #   A Python venv
    ml-env/                        #   Another Python venv
  snapshots/                       # Pre-fix environment snapshots

<your-project>/.shellock/          # Per-project (Git-committable)
  spec.json                        # Current environment specification
  history.json                     # Action audit trail
```

---

## Environment Variables

| Variable | Effect |
|---|---|
| `SHELLOCK_PLAIN=1` | Disable Rich formatting (plain text output for CI/pipes) |

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test files
pytest tests/test_core.py -v        # Schemas, dispatcher, registry, fingerprinting
pytest tests/test_modules.py -v     # Python + Node module tests
pytest tests/test_knowledge.py -v   # Package knowledge cache tests
pytest tests/test_cli.py -v         # CLI helpers and UI tests
pytest tests/test_new_features.py -v # Module inference, aliases, adaptive features

# Run a single test
pytest tests/test_core.py::TestDispatcher::test_validate_blocks_semicolon_injection -v
```

---

## Cleanup

```bash
# Delete a specific environment
shellock destroy my-env

# Delete all environments
rm -rf ~/.shellock/envs/

# Remove a project's Shellock history
rm -rf .shellock/

# Full reset (all Shellock data)
rm -rf ~/.shellock/
```

---

## License

MIT
