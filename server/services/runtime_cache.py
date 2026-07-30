from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Tuple


_CACHE: Dict[str, Tuple[float, Any]] = {}
_LOCK = asyncio.Lock()


def _normalize_key(namespace: str, key: str) -> str:
    return f"{namespace}:{key}"


async def get_cached_or_load(
    *,
    namespace: str,
    key: str,
    ttl_seconds: int,
    loader: Callable[[], Awaitable[Any]],
) -> tuple[Any, bool]:
    """
    Retorna (value, cache_hit).
    Cache em memória de processo com TTL curto para reduzir latência em leituras quentes.
    """
    now = time.monotonic()
    full_key = _normalize_key(namespace, key)
    safe_ttl = max(1, int(ttl_seconds or 1))

    async with _LOCK:
        cached = _CACHE.get(full_key)
        if cached:
            expires_at, value = cached
            if expires_at > now:
                return value, True
            _CACHE.pop(full_key, None)

    value = await loader()

    async with _LOCK:
        _CACHE[full_key] = (time.monotonic() + safe_ttl, value)

    return value, False


async def invalidate_namespace(namespace: str) -> None:
    prefix = f"{namespace}:"
    async with _LOCK:
        keys = [k for k in _CACHE.keys() if k.startswith(prefix)]
        for key in keys:
            _CACHE.pop(key, None)
