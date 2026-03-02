"""
Azure AI Foundry LLM client wrapper.

Features:
- Gated calls: only invoked when triage score ≥ threshold
- Response caching via SHA-256 prompt hash
- Token limit enforcement
- Prompt hash stored (never raw prompt) for audit
- Graceful fallback when endpoint is unavailable
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

from .cache import ResponseCache

logger = logging.getLogger(__name__)


class LLMClient:
    """Wrapper around Azure AI Foundry (OpenAI-compatible) endpoint."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        max_tokens: int = 1024,
        temperature: float = 0.1,
        triage_threshold: float = 0.7,
        max_calls_per_batch: int = 50,
        cache: ResponseCache | None = None,
    ) -> None:
        self.endpoint = endpoint or os.getenv("AZURE_AI_ENDPOINT", "")
        self.api_key = api_key or os.getenv("AZURE_AI_API_KEY", "")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.triage_threshold = triage_threshold
        self.max_calls_per_batch = max_calls_per_batch
        self._call_count = 0
        self._cache = cache or ResponseCache()
        self._client = None

        if self.endpoint and self.api_key:
            try:
                from openai import AzureOpenAI

                self._client = AzureOpenAI(
                    azure_endpoint=self.endpoint,
                    api_key=self.api_key,
                    api_version="2024-06-01",
                )
                logger.info("LLMClient: connected to Azure AI Foundry (%s)", self.endpoint)
            except Exception as exc:
                logger.warning("LLMClient: init failed (%s), LLM calls will be unavailable", exc)
        else:
            logger.info("LLMClient: no endpoint configured — running in rules-only mode")

    def should_call(self, triage_score: float) -> bool:
        """Check whether an LLM call is warranted based on triage score and budget."""
        if triage_score < self.triage_threshold:
            return False
        if self._call_count >= self.max_calls_per_batch:
            logger.warning("LLM call budget exhausted (%d/%d)", self._call_count, self.max_calls_per_batch)
            return False
        return True

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Call the LLM with caching and cost controls.

        Returns:
            {
                "response": str,
                "prompt_hash": str,
                "cached": bool,
                "latency_ms": float,
                "model": str,
            }
        """
        prompt_hash = self._cache.prompt_hash(system_prompt, user_prompt)
        cache_key = self._cache.make_key(self.model, system_prompt, user_prompt)

        # Check cache
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug("Cache hit for prompt_hash=%s", prompt_hash[:12])
                return {
                    "response": cached,
                    "prompt_hash": prompt_hash,
                    "cached": True,
                    "latency_ms": 0.0,
                    "model": self.model,
                }

        # Call LLM
        start = time.monotonic()
        response_text = self._invoke(system_prompt, user_prompt)
        latency_ms = (time.monotonic() - start) * 1000

        self._call_count += 1

        # Cache response
        if use_cache and response_text:
            self._cache.put(cache_key, response_text)

        return {
            "response": response_text,
            "prompt_hash": prompt_hash,
            "cached": False,
            "latency_ms": latency_ms,
            "model": self.model,
        }

    def _invoke(self, system_prompt: str, user_prompt: str) -> str:
        """Actually invoke the LLM endpoint."""
        if not self._client:
            logger.warning("LLM client not available — returning fallback response")
            return self._fallback_response(user_prompt)

        try:
            completion = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            return completion.choices[0].message.content or ""
        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            return self._fallback_response(user_prompt)

    @staticmethod
    def _fallback_response(user_prompt: str) -> str:
        """Deterministic fallback when LLM is unavailable."""
        return (
            "LLM endpoint unavailable. Based on rules-only analysis, "
            "this transaction requires manual review. Escalating to human analyst."
        )

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def cache_stats(self) -> Dict[str, int]:
        return self._cache.stats
