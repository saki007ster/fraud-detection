"""
Response cache — maps SHA-256(prompt) → cached LLM response.

Uses an in-memory LRU cache.  Thread-safe via a lock.
An optional Redis backend can be added in Phase 2.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional


class ResponseCache:
    """LRU cache keyed by SHA-256 hash of (model + system_prompt + user_prompt)."""

    def __init__(self, max_size: int = 256, ttl_seconds: int = 3600) -> None:
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def make_key(model: str, system_prompt: str, user_prompt: str) -> str:
        """Create a privacy-safe cache key from prompts."""
        payload = json.dumps(
            {"model": model, "system": system_prompt, "user": user_prompt},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def prompt_hash(system_prompt: str, user_prompt: str) -> str:
        """Return SHA-256 of a prompt pair (for audit logs, not caching)."""
        payload = f"{system_prompt}||{user_prompt}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._hits += 1
                return self._cache[key]["response"]
            self._misses += 1
            return None

    def put(self, key: str, response: str) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = {"response": response}
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    @property
    def stats(self) -> Dict[str, int]:
        return {"hits": self._hits, "misses": self._misses, "size": len(self._cache)}
