from __future__ import annotations

import asyncio
import time
import sys
from typing import Any, Awaitable, Callable, Dict, Tuple


_CACHE: Dict[str, Tuple[float, Any]] = {}
_INFLIGHT: Dict[str, asyncio.Task[Any]] = {}
_LOCK = asyncio.Lock()
# Estimated payload budget: 32 entries x 256 KiB; excludes allocator overhead.
_MAX_ENTRIES = 32
_MAX_ENTRY_BYTES = 256 * 1024
_EXPIRY_HANDLE = None


def _fits_entry_budget(value: Any) -> bool:
    pending = [value]
    seen = set()
    size = 0
    while pending:
        item = pending.pop()
        identity = id(item)
        if identity in seen:
            continue
        seen.add(identity)
        size += sys.getsizeof(item)
        if size > _MAX_ENTRY_BYTES or len(seen) > 10000:
            return False
        if isinstance(item, dict):
            if len(item) > 10000:
                return False
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple, set, frozenset)):
            if len(item) > 10000:
                return False
            pending.extend(item)
        elif not isinstance(item, (str, bytes, int, float, bool, type(None))):
            return False
    return True


def _expire_entries() -> None:
    global _EXPIRY_HANDLE
    now = time.monotonic()
    for key in list(_CACHE):
        if _CACHE[key][0] <= now:
            _CACHE.pop(key, None)
    _EXPIRY_HANDLE = None
    if _CACHE:
        delay = max(0.01, min(entry[0] for entry in _CACHE.values()) - now)
        _EXPIRY_HANDLE = asyncio.get_running_loop().call_later(delay, _expire_entries)


def _schedule_expiry() -> None:
    global _EXPIRY_HANDLE
    if _EXPIRY_HANDLE is not None:
        _EXPIRY_HANDLE.cancel()
    _expire_entries()


async def _load(full_key, ttl, loader):
    # The task owns cleanup even if every HTTP waiter is cancelled.
    try:
        value = await loader()
        if _fits_entry_budget(value):
            async with _LOCK:
                while len(_CACHE) >= _MAX_ENTRIES:
                    _CACHE.pop(next(iter(_CACHE)))
                _CACHE[full_key] = (time.monotonic() + ttl, value)
                _schedule_expiry()
        return value
    finally:
        async with _LOCK:
            if _INFLIGHT.get(full_key) is asyncio.current_task():
                _INFLIGHT.pop(full_key, None)



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

        task = _INFLIGHT.get(full_key)
        if task is None:
            task = asyncio.create_task(_load(full_key, safe_ttl, loader))
            task.add_done_callback(_consume_exception)
            _INFLIGHT[full_key] = task

    return await asyncio.shield(task), False


def _consume_exception(task):
    if not task.cancelled():
        task.exception()


async def invalidate_namespace(namespace: str) -> None:
    prefix = f"{namespace}:"
    async with _LOCK:
        keys = [k for k in _CACHE.keys() if k.startswith(prefix)]
        for key in keys:
            _CACHE.pop(key, None)
