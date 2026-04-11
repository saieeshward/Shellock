"""LLM interface — the only place Shellock talks to a language model.

The LLM is isolated behind this single module.  It does text→JSON
conversion only.  It never executes commands, never touches files,
never makes decisions.  Every output is validated by Pydantic before
it reaches the user.

Resolution order:
    1. Local LLM (Ollama) — private, offline
    2. Cloud LLM (litellm) — requires API key + internet
    3. Template fallback — no LLM at all
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ValidationError

from shellock_core.core.schemas import LLMTier, ShelllockConfig

logger = logging.getLogger(__name__)

# Maximum retries with validation feedback
MAX_RETRIES = 3

# ── Prompt templates ────────────────────────────────────────────

SPEC_PROMPT = """You are Shellock, an environment setup assistant.
Convert the user's request into a JSON environment specification.

SYSTEM CONTEXT:
{system_context}

USER PREFERENCES:
{user_preferences}

PROJECT STATE:
{project_context}

{few_shot_section}RESPOND WITH ONLY VALID JSON matching this schema:
{{
    "env_id": "short-memorable-name",
    "module": "{module_name}",
    "runtime_version": "version or null",
    "packages": [
        {{"name": "package-name", "version": null, "extras": [], "reason": "why this package was chosen for the user's specific request (e.g. 'chosen for parsing HTML from scraped pages, as requested' not 'HTML parser'); reference what the user asked for"}}
    ],
    "env_vars": {{}},
    "post_hooks": [],
    "reasoning": "Brief explanation of your overall choices"
}}

IMPORTANT — env_id naming rules:
- Use 2-3 words in kebab-case (e.g. "fastapi-dev", "react-ts-app", "ml-research", "data-pipeline")
- Make it descriptive of the project purpose, NOT generic
- Avoid: "python-env", "my-project", "new-env", "shellock-env"

USER REQUEST: {description}

JSON:"""

NAME_PROMPT = """Generate a short, memorable environment name.

USER REQUEST: {description}
PACKAGES: {packages}

Rules:
- 2-3 words in kebab-case (lowercase, hyphens only — no underscores or spaces)
- Descriptive of purpose: e.g. "fastapi-dev", "react-ts-app", "ml-research", "data-pipeline"
- NOT generic: avoid "python-env", "my-project", "new-environment", "env-1"

Respond with ONLY the name on a single line, nothing else:"""

ERROR_PROMPT = """You are Shellock, an environment error diagnostician.
Analyse this error and propose a fix as JSON.

SYSTEM CONTEXT:
{system_context}

ERROR OUTPUT:
{stderr}

RECENT ACTIONS IN THIS PROJECT:
{recent_actions}

RESPOND WITH ONLY VALID JSON:
{{
    "diagnosed": true,
    "fix": {{
        "action": "install|upgrade|downgrade|remove|configure",
        "package": "package-name or null",
        "to": "target version or null",
        "commands": ["exact commands to run"]
    }},
    "reasoning": "Why this fix should work"
}}

If you cannot diagnose the error, respond with:
{{"diagnosed": false, "suggestions": ["suggestions for the user"]}}

JSON:"""


# ── LLM Client ──────────────────────────────────────────────────


class LLMClient:
    """Unified interface for LLM providers.

    Handles Ollama (local), litellm (cloud via Gemini), and template fallback.
    Implements the tier chain: Ollama → Gemini 2.0 Flash → Template.
    All methods return validated Pydantic models or raw dicts.
    """

    # Default cloud model for Gemini free tier via litellm
    CLOUD_MODEL = "gemini/gemini-2.0-flash"

    def __init__(self, config: ShelllockConfig, tier: LLMTier, ollama_model: str | None = None) -> None:
        self.config = config
        self.tier = tier
        self._ollama_model = ollama_model  # System-detected Ollama model; overrides config for LOCAL tier
        self._ollama_client = None
        self._litellm = None

    def is_available(self) -> bool:
        """Check if any LLM backend is currently reachable."""
        if self.tier == LLMTier.TEMPLATE:
            return False
        if self.tier == LLMTier.LOCAL:
            return self._check_ollama() or self._cloud_available()
        if self.tier == LLMTier.CLOUD:
            return self._cloud_available()
        return False

    def _cloud_available(self) -> bool:
        """Check if cloud LLM (Gemini) is configured."""
        return self.config.llm_api_key is not None

    def generate_spec(
        self,
        description: str,
        module_name: str,
        system_context: dict[str, Any],
        user_preferences: dict[str, Any],
        project_context: dict[str, Any],
        few_shot_examples: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Convert natural language to an environment spec dict.

        Returns a validated dict on success, None if the LLM fails
        after MAX_RETRIES attempts.
        """
        if few_shot_examples:
            example_lines = ["PAST APPROVED ENVIRONMENTS (use as style examples):"]
            for ex in few_shot_examples[:3]:
                pkgs = ", ".join(p["name"] if isinstance(p, dict) else str(p) for p in ex.get("packages", []))
                example_lines.append(
                    f'  - {ex.get("env_id", "?")} | runtime={ex.get("runtime_version")} | packages={pkgs}'
                )
            few_shot_section = "\n".join(example_lines) + "\n\n"
        else:
            few_shot_section = ""

        prompt = SPEC_PROMPT.format(
            system_context=json.dumps(system_context, indent=2),
            user_preferences=json.dumps(user_preferences, indent=2),
            project_context=json.dumps(project_context, indent=2),
            module_name=module_name,
            description=description,
            few_shot_section=few_shot_section,
        )
        return self._generate_with_retry(prompt)

    def generate_env_name(self, description: str, packages: list[str]) -> str | None:
        """Generate a short, memorable environment name from a description.

        Returns a sanitized kebab-case name, or None if the LLM fails.
        """
        import re

        prompt = NAME_PROMPT.format(
            description=description,
            packages=", ".join(packages) if packages else "none specified",
        )
        raw = self._call_llm(prompt)
        if not raw:
            return None
        # Take the first line, strip whitespace, lowercase
        name = raw.strip().split("\n")[0].strip().lower()
        # Only accept valid kebab-case names of reasonable length
        if re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", name) and 3 <= len(name) <= 40:
            return name
        return None

    def diagnose_error(
        self,
        stderr: str,
        system_context: dict[str, Any],
        recent_actions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Analyse an error and propose a fix.

        Returns a diagnosis dict on success, None if the LLM fails.
        """
        prompt = ERROR_PROMPT.format(
            system_context=json.dumps(system_context, indent=2),
            stderr=stderr,
            recent_actions=json.dumps(recent_actions[-5:], indent=2, default=str),
        )
        return self._generate_with_retry(prompt)

    # ── Private ─────────────────────────────────────────────────

    def _generate_with_retry(self, prompt: str) -> dict[str, Any] | None:
        """Call the LLM with validation-error feedback on retries."""
        current_prompt = prompt

        for attempt in range(1, MAX_RETRIES + 1):
            raw = self._call_llm(current_prompt)
            if raw is None:
                logger.warning("LLM returned no response (attempt %d/%d)", attempt, MAX_RETRIES)
                continue

            parsed = self._extract_json(raw)
            if parsed is not None:
                return parsed

            # Feed validation error back to the LLM for next attempt
            current_prompt = (
                prompt
                + f"\n\nYour previous output was not valid JSON. "
                f"Attempt {attempt}/{MAX_RETRIES}. "
                f"Return ONLY valid JSON, no markdown, no explanation."
            )
            logger.warning("LLM output not valid JSON (attempt %d/%d)", attempt, MAX_RETRIES)

        logger.error("LLM failed after %d attempts", MAX_RETRIES)
        return None

    def _call_llm(self, prompt: str) -> str | None:
        """Dispatch to LLM with fallback chain: Ollama → Gemini → None."""
        if self.tier == LLMTier.LOCAL:
            result = self._call_ollama(prompt)
            if result is not None:
                return result
            # Ollama failed — fall through to cloud
            if self._cloud_available():
                logger.info("Ollama unavailable, falling back to Gemini cloud")
                return self._call_litellm(prompt)
            return None
        if self.tier == LLMTier.CLOUD:
            return self._call_litellm(prompt)
        return None

    def _call_ollama(self, prompt: str) -> str | None:
        """Call Ollama's local API."""
        try:
            import ollama

            # Use the system-detected Ollama model if available; fall back to config model.
            # config.llm_model may hold a cloud model name (e.g. "gemini/gemini-1.5-flash")
            # when the user configured a cloud provider but Ollama is also running.
            model = self._ollama_model or self.config.llm_model

            response = ollama.generate(
                model=model,
                prompt=prompt,
                options={"temperature": 0.1},  # low temp for structured output
            )
            return response.get("response", "")
        except ImportError:
            logger.error("ollama package not installed")
            return None
        except Exception as e:
            logger.error("Ollama call failed: %s", e)
            return None

    # Maximum seconds to wait before retrying a rate-limited request
    _RATE_LIMIT_RETRY_MAX_WAIT = 30

    def _call_litellm(self, prompt: str) -> str | None:
        """Call a cloud LLM via litellm with quota-aware fallback.

        Resolution order:
            1. Primary model (config.llm_model)
            2. On transient rate-limit (delay ≤ 30 s): wait, then retry primary
            3. On quota exhaustion or retry failure: try fallback model/key
               (config.llm_fallback_model + config.llm_fallback_key)
        """
        import re
        import time

        try:
            import litellm
        except ImportError:
            logger.error("litellm package not installed (pip install shellock[cloud])")
            return None

        model = self.config.llm_model or self.CLOUD_MODEL

        def _complete(m: str, key: str | None) -> str | None:
            response = litellm.completion(
                model=m,
                messages=[{"role": "user", "content": prompt}],
                api_key=key,
                temperature=0.1,
            )
            return response.choices[0].message.content

        def _retry_delay(exc: Exception) -> float | None:
            """Extract retry delay in seconds from a RateLimitError, or None."""
            text = str(exc)
            m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', text)
            if m:
                return float(m.group(1))
            m = re.search(r'retry in (\d+(?:\.\d+)?)s', text, re.IGNORECASE)
            if m:
                return float(m.group(1))
            return None

        # ── Attempt 1: primary model ──────────────────────────────
        try:
            return _complete(model, self.config.llm_api_key)
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = "ratelimit" in err_str or "rate_limit" in err_str or "429" in err_str
            is_quota = "quota" in err_str or "resource_exhausted" in err_str

            if is_rate_limit and not is_quota:
                # Transient rate limit — wait if delay is short, then retry primary
                delay = _retry_delay(e)
                if delay is not None and delay <= self._RATE_LIMIT_RETRY_MAX_WAIT:
                    logger.warning("Rate limited; retrying primary in %.0fs", delay)
                    time.sleep(delay)
                    try:
                        return _complete(model, self.config.llm_api_key)
                    except Exception as e2:
                        logger.error("Cloud LLM call failed after retry: %s", e2)
                else:
                    logger.error("Cloud LLM call failed: %s", e)
            else:
                logger.error("Cloud LLM call failed: %s", e)

        # ── Attempt 2: fallback model/key ─────────────────────────
        if self.config.llm_fallback_model and self.config.llm_fallback_key:
            logger.info("Trying fallback cloud model: %s", self.config.llm_fallback_model)
            try:
                return _complete(self.config.llm_fallback_model, self.config.llm_fallback_key)
            except Exception as e:
                logger.error("Fallback cloud LLM call failed: %s", e)

        return None

    def _check_ollama(self) -> bool:
        """Quick check if Ollama is responding."""
        try:
            import ollama

            ollama.list()
            return True
        except Exception:
            return False
        
    def explain_action(
            self,
            action_record: dict[str, Any],
            recent_actions: list[dict[str, Any]] | None = None,
        ) -> str | None:
            prompt = f"""
        You are explaining the most recent change made by a CLI environment repair tool called Shellock.

        Explain this change in natural language for a developer.

        Rules:
        - Be concise but clear.
        - Say what Shellock changed.
        - Explain why it likely made that change.
        - Mention whether it succeeded or failed.
        - Do not invent actions, files, or reasons that are not supported by the data.
        - If the action data is incomplete, say so briefly.
        - Prefer plain English over jargon.

        Action record:
        {json.dumps(action_record, indent=2, default=str)}

        Recent actions:
        {json.dumps(recent_actions or [action_record], indent=2, default=str)}
        """.strip()

            return self._call_llm(prompt)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """Extract a JSON object from LLM output (handles markdown fences)."""
        text = text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (fences)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in the text
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        return None
