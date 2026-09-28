"""Process-local and optional Redis caches for registered aggregate metrics."""

import hashlib
import json
import logging
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any

logger = logging.getLogger(__name__)


def database_signature(database_path: str | Path) -> tuple[tuple[Any, ...], ...]:
    """Return a file signature that changes when SQLite data or WAL changes."""
    signatures = []
    for path in (
        Path(database_path),
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-journal"),
    ):
        try:
            stat = path.stat()
            signatures.append(
                (
                    str(path),
                    stat.st_dev,
                    stat.st_ino,
                    stat.st_size,
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                )
            )
        except FileNotFoundError:
            signatures.append((str(path), None))
    return tuple(signatures)


class MetricResultCache:
    def __init__(self, *, max_entries: int = 256, ttl_seconds: float = 30):
        if max_entries < 1 or ttl_seconds <= 0:
            raise ValueError("Cache limits must be positive")
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._entries: OrderedDict[tuple[Any, ...], tuple[float, dict[str, Any]]] = (
            OrderedDict()
        )
        self._lock = RLock()

    def get(self, key: tuple[Any, ...]) -> dict[str, Any] | None:
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, result = entry
            if expires_at <= now:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return deepcopy(result)

    def set(self, key: tuple[Any, ...], result: dict[str, Any]) -> None:
        with self._lock:
            self._entries[key] = (monotonic() + self.ttl_seconds, deepcopy(result))
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)


class RedisMetricResultCache:
    """Shared TTL cache; callers must keep authorization in every cache key."""

    def __init__(self, client: Any, *, ttl_seconds: float = 30):
        if ttl_seconds <= 0:
            raise ValueError("Cache limits must be positive")
        self.client = client
        self.ttl_seconds = ttl_seconds
        self.namespace = "dbgpt:enterprise-text2sql:metric:v1"

    def _key(self, key: tuple[Any, ...]) -> str:
        serialized = json.dumps(key, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return f"{self.namespace}:{digest}"

    def get(self, key: tuple[Any, ...]) -> dict[str, Any] | None:
        try:
            value = self.client.get(self._key(key))
            if value is None:
                return None
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            result = json.loads(value)
            if not isinstance(result, dict):
                logger.warning("Shared metric cache returned an invalid payload")
                return None
            return result
        except Exception:
            logger.warning("Shared metric cache read failed; bypassing cache")
            return None

    def set(self, key: tuple[Any, ...], result: dict[str, Any]) -> None:
        try:
            value = json.dumps(result, separators=(",", ":"), allow_nan=False)
            ttl_ms = max(1, int(self.ttl_seconds * 1000))
            self.client.set(self._key(key), value, px=ttl_ms)
        except Exception:
            logger.warning("Shared metric cache write failed; bypassing cache")


def build_metric_cache(redis_url: str | None = None):
    """Use Redis when configured; otherwise keep the local bounded cache."""
    if not redis_url:
        return MetricResultCache()
    try:
        import redis
    except ImportError as exc:
        raise RuntimeError(
            "Install redis-py to enable DBGPT_METRIC_CACHE_REDIS_URL"
        ) from exc
    client = redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    return RedisMetricResultCache(client)
