import os
from typing import Any


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == '':
        return default
    return int(raw)


def load_config() -> dict[str, Any]:
    """Abuse-control settings, every one overridable through an env var so the
    Docker image stays a single self-contained container."""
    return {
        'MAX_CONTENT_LENGTH': _env_int('FLAMAPY_MAX_CONTENT_LENGTH', 16 * 1024 * 1024),
        'RATELIMIT_ENABLED': _env_bool('FLAMAPY_RATELIMIT_ENABLED', True),
        'RATELIMIT_STORAGE_URI': os.environ.get('FLAMAPY_RATELIMIT_STORAGE_URI', 'memory://'),
        'RATELIMIT_DEFAULT_OPERATION': os.environ.get(
            'FLAMAPY_RATELIMIT_DEFAULT', '60 per minute'
        ),
        'RATELIMIT_EXPENSIVE_OPERATION': os.environ.get(
            'FLAMAPY_RATELIMIT_EXPENSIVE', '10 per minute'
        ),
        'OPERATION_TIMEOUT': _env_int('FLAMAPY_OPERATION_TIMEOUT', 60),
        'CACHE_TTL': _env_int('FLAMAPY_CACHE_TTL', 3600),
        'CACHE_MAXSIZE': _env_int('FLAMAPY_CACHE_MAXSIZE', 128),
        'TRUST_PROXY': _env_bool('FLAMAPY_TRUST_PROXY', False),
    }
