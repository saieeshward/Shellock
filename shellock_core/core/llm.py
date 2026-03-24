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

RESPOND WITH ONLY VALID JSON matching this schema:
{{
    "env_id": "short-descriptive-id",
    "module": "{module_name}",
    "runtime_version": "version or null",
    "packages": [
        {{"name": "package-name", "version": null, "extras": []}}
    ],
    "env_vars": {{}},
    "post_hooks": [],
    "reasoning": "Brief explanation of your choices"
}}

USER REQUEST: {description}

JSON:"""

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

    def __init__(self, config: ShelllockConfig, tier: LLMTier) -> None:
        self.config = config
        self.tier = tier
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
    ) -> dict[str, Any] | None:
        """Convert natural language to an environment spec dict.

        Returns a validated dict on success, None if the LLM fails
        after MAX_RETRIES attempts.
        """
        prompt = SPEC_PROMPT.format(
            system_context=json.dumps(system_context, indent=2),
            user_preferences=json.dumps(user_preferences, indent=2),
            project_context=json.dumps(project_context, indent=2),
            module_name=module_name,
            description=description,
        )
        return self._generate_with_retry(prompt)

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

            response = ollama.generate(
                model=self.config.llm_model,
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

    def _call_litellm(self, prompt: str) -> str | None:
        """Call a cloud LLM via litellm (defaults to Gemini 2.0 Flash)."""
        try:
            import litellm

            # Use Gemini model for cloud tier, unless user overrode in config
            model = self.CLOUD_MODEL
            if self.tier == LLMTier.CLOUD and self.config.llm_model and "gemini" not in self.config.llm_model:
                # User set a custom cloud model — respect it
                model = self.config.llm_model

            response = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                api_key=self.config.llm_api_key,
                temperature=0.1,
            )
            return response.choices[0].message.content
        except ImportError:
            logger.error("litellm package not installed (pip install shellock[cloud])")
            return None
        except Exception as e:
            logger.error("Cloud LLM call failed: %s", e)
            return None

    def _check_ollama(self) -> bool:
        """Quick check if Ollama is responding."""
        try:
            import ollama

            ollama.list()
            return True
        except Exception:
            return False

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
