"""Serper web search integration — optional, user-gated.

Used to enrich package resolution when LLM or templates can't
confidently identify the right packages for an obscure request.

Usage is always opt-in:
  1. User must configure a Serper API key (shellock config serper_api_key <key>)
  2. During init, Shellock prompts: "Use web search to find packages? [yes/no]"
  3. Only if the user says yes does this module make any network request.

Security note: the Serper API key is stored in plaintext at
~/.shellock/config.json with permissions 600 (owner read/write only).

Install: pip install shellock[serper]
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"


def is_available() -> bool:
    """Check if the requests library is installed (required for Serper)."""
    try:
        import requests  # noqa: F401
        return True
    except ImportError:
        return False


def search_packages(query: str, api_key: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search Serper for Python packages relevant to the query.

    Returns a list of results, each with 'title', 'snippet', 'link'.
    Returns [] on any error — caller should degrade gracefully.
    """
    if not is_available():
        logger.warning("requests not installed — Serper search unavailable. Run: pip install shellock[serper]")
        return []

    import requests

    try:
        resp = requests.post(
            SERPER_URL,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f"python pypi packages for {query}", "num": max_results},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "link": item.get("link", ""),
            }
            for item in data.get("organic", [])[:max_results]
        ]
    except Exception as e:
        logger.warning("Serper search failed: %s", e)
        return []


def extract_package_hints(results: list[dict[str, Any]]) -> list[str]:
    """Extract likely PyPI package names from search result snippets.

    Looks for patterns like 'pip install <name>' or 'pypi.org/project/<name>'
    in the snippets and titles.
    """
    import re

    hints: list[str] = []
    pip_pattern = re.compile(r"pip install\s+([\w\-]+)", re.IGNORECASE)
    pypi_pattern = re.compile(r"pypi\.org/project/([\w\-]+)", re.IGNORECASE)

    for result in results:
        text = result.get("title", "") + " " + result.get("snippet", "") + " " + result.get("link", "")
        hints.extend(pip_pattern.findall(text))
        hints.extend(pypi_pattern.findall(text))

    # Deduplicate and normalise to lowercase, preserve order
    seen: set[str] = set()
    unique: list[str] = []
    for h in hints:
        name = h.lower().strip()
        if name and name not in seen:
            seen.add(name)
            unique.append(name)

    return unique
