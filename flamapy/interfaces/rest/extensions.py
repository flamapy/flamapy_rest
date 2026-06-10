import threading
from typing import Any, Optional

from cachetools import TTLCache
from flask import Flask, current_app
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def default_operation_limit() -> str:
    return current_app.config['RATELIMIT_DEFAULT_OPERATION']


def expensive_operation_limit() -> str:
    return current_app.config['RATELIMIT_EXPENSIVE_OPERATION']


# Storage URI and enabled flag are picked up from app.config (RATELIMIT_*)
# during init_app; per-route limits are attached in operations_routes.
limiter = Limiter(key_func=get_remote_address)


class ResultCache:
    """Per-process TTL cache for operation results. The cache object is created
    on init_app so its size/TTL follow the app configuration; a TTL of 0
    disables caching entirely."""

    def __init__(self) -> None:
        self._cache: Optional[TTLCache[str, Any]] = None
        self._lock = threading.Lock()

    def init_app(self, app: Flask) -> None:
        ttl = app.config['CACHE_TTL']
        if ttl > 0:
            self._cache = TTLCache(maxsize=app.config['CACHE_MAXSIZE'], ttl=ttl)
        else:
            self._cache = None

    def get(self, key: str) -> Any:
        if self._cache is None:
            return None
        with self._lock:
            return self._cache.get(key)

    def set(self, key: str, value: Any) -> None:
        if self._cache is None:
            return
        with self._lock:
            self._cache[key] = value


result_cache = ResultCache()
