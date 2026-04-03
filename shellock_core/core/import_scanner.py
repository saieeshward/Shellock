"""AST-based import scanner for brownfield projects.

Scans Python source files to infer what packages are needed, even
when there's no requirements.txt or pyproject.toml.

Maps import names to PyPI package names (e.g. cv2 → opencv-python)
so the result can be fed directly into spec generation.

Used by shellock init when no dependency files are detected.
"""

from __future__ import annotations

import ast
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Import name → PyPI install name for common mismatches
IMPORT_TO_PYPI: dict[str, str] = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "bs4": "beautifulsoup4",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "attr": "attrs",
    "google.cloud": "google-cloud",
    "google.auth": "google-auth",
    "jwt": "PyJWT",
    "Crypto": "pycryptodome",
    "serial": "pyserial",
    "gi": "PyGObject",
    "wx": "wxPython",
    "usb": "pyusb",
    "magic": "python-magic",
    "telegram": "python-telegram-bot",
    "discord": "discord.py",
    "stripe": "stripe",
    "twilio": "twilio",
    "sendgrid": "sendgrid",
    "boto3": "boto3",
    "botocore": "botocore",
    "paramiko": "paramiko",
    "nacl": "PyNaCl",
    "OpenSSL": "pyOpenSSL",
    "pygments": "Pygments",
    "docutils": "docutils",
    "jinja2": "Jinja2",
    "markupsafe": "MarkupSafe",
    "werkzeug": "Werkzeug",
    "itsdangerous": "itsdangerous",
    "click": "click",
    "typer": "typer",
    "rich": "rich",
    "pydantic": "pydantic",
    "sqlalchemy": "SQLAlchemy",
    "alembic": "alembic",
    "celery": "celery",
    "kombu": "kombu",
    "redis": "redis",
    "pymongo": "pymongo",
    "motor": "motor",
    "aiohttp": "aiohttp",
    "httpx": "httpx",
    "requests": "requests",
    "urllib3": "urllib3",
    "certifi": "certifi",
    "chardet": "chardet",
    "charset_normalizer": "charset-normalizer",
    "multipart": "python-multipart",
    "starlette": "starlette",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "gunicorn": "gunicorn",
    "flask": "Flask",
    "django": "Django",
    "tornado": "tornado",
    "sanic": "sanic",
    "litestar": "litestar",
    "numpy": "numpy",
    "pandas": "pandas",
    "matplotlib": "matplotlib",
    "seaborn": "seaborn",
    "plotly": "plotly",
    "scipy": "scipy",
    "statsmodels": "statsmodels",
    "torch": "torch",
    "torchvision": "torchvision",
    "torchaudio": "torchaudio",
    "tensorflow": "tensorflow",
    "keras": "keras",
    "transformers": "transformers",
    "datasets": "datasets",
    "tokenizers": "tokenizers",
    "diffusers": "diffusers",
    "accelerate": "accelerate",
    "peft": "peft",
    "langchain": "langchain",
    "openai": "openai",
    "anthropic": "anthropic",
    "tiktoken": "tiktoken",
    "pytest": "pytest",
    "hypothesis": "hypothesis",
    "mock": "mock",
    "freezegun": "freezegun",
    "factory_boy": "factory-boy",
    "faker": "Faker",
    "psutil": "psutil",
    "tqdm": "tqdm",
    "loguru": "loguru",
    "structlog": "structlog",
    "arrow": "arrow",
    "pendulum": "pendulum",
    "pytz": "pytz",
    "toml": "toml",
    "tomli": "tomli",
    "orjson": "orjson",
    "msgpack": "msgpack",
    "cryptography": "cryptography",
    "bcrypt": "bcrypt",
    "passlib": "passlib",
}

# Standard library top-level modules — these are never PyPI packages
_STDLIB: frozenset[str] = frozenset(
    getattr(sys, "stdlib_module_names", set())  # Python 3.10+
) | {
    # Fallback for older Python — common stdlib modules
    "abc", "ast", "asyncio", "builtins", "collections", "concurrent",
    "contextlib", "copy", "csv", "dataclasses", "datetime", "decimal",
    "email", "enum", "functools", "gc", "glob", "hashlib", "hmac",
    "html", "http", "importlib", "inspect", "io", "itertools", "json",
    "keyword", "linecache", "logging", "math", "multiprocessing", "operator",
    "os", "pathlib", "pickle", "platform", "pprint", "queue", "random",
    "re", "shlex", "shutil", "signal", "socket", "sqlite3", "ssl",
    "stat", "string", "struct", "subprocess", "sys", "tempfile",
    "textwrap", "threading", "time", "timeit", "traceback", "types",
    "typing", "unicodedata", "unittest", "urllib", "uuid", "warnings",
    "weakref", "xml", "xmlrpc", "zipfile", "zlib",
}


def scan_project_imports(project_path: str, max_files: int = 200) -> list[str]:
    """Scan .py files in a project and return likely PyPI package names.

    Args:
        project_path: Root directory to scan.
        max_files: Cap on files scanned (avoids runaway on huge repos).

    Returns:
        Sorted list of PyPI package names inferred from imports.
    """
    root = Path(project_path)
    py_files = _collect_py_files(root, max_files)

    if not py_files:
        return []

    raw_imports: set[str] = set()

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_extract_imports, f): f for f in py_files}
        for future in as_completed(futures):
            try:
                raw_imports.update(future.result())
            except Exception as e:
                logger.debug("Import scan error on %s: %s", futures[future], e)

    return _resolve_to_pypi(raw_imports, project_root=root)


def _collect_py_files(root: Path, limit: int) -> list[Path]:
    """Find Python files, skipping venv dirs and hidden directories."""
    skip_dirs = {".venv", "venv", "env", ".env", ".git", "__pycache__",
                 "node_modules", ".tox", "dist", "build", ".eggs", "site-packages"}
    files: list[Path] = []
    for path in root.rglob("*.py"):
        # Skip if any parent dir is in skip list
        if any(part in skip_dirs for part in path.parts):
            continue
        files.append(path)
        if len(files) >= limit:
            logger.warning(
                "Import scan capped at %d files — results may be incomplete", limit
            )
            break
    return files


def _extract_imports(file_path: Path) -> set[str]:
    """Parse a single Python file and return top-level import names."""
    try:
        source = file_path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, ValueError):
        return set()

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Take top-level name: "numpy.linalg" → "numpy"
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:  # absolute imports only
                imports.add(node.module.split(".")[0])
    return imports


def _resolve_to_pypi(
    raw_imports: set[str], project_root: Path | None = None
) -> list[str]:
    """Filter stdlib, map to PyPI names, return sorted list.

    Args:
        raw_imports: Top-level module names extracted from source files.
        project_root: If provided, local .py stems and package dirs at the
            root are excluded so Shellock doesn't mistake them for PyPI deps.
    """
    # Build a set of local module names to skip
    local_names: set[str] = set()
    if project_root is not None and project_root.is_dir():
        for item in project_root.iterdir():
            if item.suffix == ".py":
                local_names.add(item.stem)
            elif item.is_dir() and (item / "__init__.py").exists():
                local_names.add(item.name)

    packages: set[str] = set()
    for name in raw_imports:
        if name in _STDLIB:
            continue
        if name in local_names:
            continue
        # Map known mismatches first
        pypi_name = IMPORT_TO_PYPI.get(name)
        if pypi_name:
            packages.add(pypi_name)
        else:
            # Use the import name as-is (works for most packages)
            packages.add(name)
    return sorted(packages, key=str.lower)


def summarise_scan(project_path: str, max_files: int = 200) -> dict[str, Any]:
    """Return a summary dict suitable for display and LLM context."""
    root = Path(project_path)
    py_files = _collect_py_files(root, max_files)
    truncated = len(py_files) >= max_files
    packages = scan_project_imports(project_path, max_files)
    return {
        "scanned": True,
        "inferred_packages": packages,
        "count": len(packages),
        "source": "ast_import_scan",
        "truncated": truncated,
    }
