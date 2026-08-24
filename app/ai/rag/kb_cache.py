"""KB version tracking for FAQ query cache invalidation."""

from __future__ import annotations

from app.utils.redis_service import cache_get, cache_set

_KB_VERSION_TTL = 86400 * 365


def kb_version_key(hospital_id: int) -> str:
    return f"voice:faq:kb_version:{hospital_id}"


async def get_kb_version(hospital_id: int) -> int:
    """Return current KB version for a hospital (0 if unset)."""
    raw = await cache_get(kb_version_key(hospital_id))
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


async def bump_kb_version(hospital_id: int) -> int:
    """Increment KB version so query-answer caches with old version are ignored."""
    new_version = await get_kb_version(hospital_id) + 1
    await cache_set(kb_version_key(hospital_id), new_version, ttl=_KB_VERSION_TTL)
    return new_version
