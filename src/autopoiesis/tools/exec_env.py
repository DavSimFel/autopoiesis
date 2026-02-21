"""Environment sanitization helpers for shell execution tools."""

from __future__ import annotations

import os

_DANGEROUS_ENV_VARS: frozenset[str] = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "DATABASE_URL",
        "DB_PASSWORD",
        "GITHUB_TOKEN",
        "LD_PRELOAD",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "PASSWORD",
        "PRIVATE_KEY",
        "PYTHONPATH",
        "SECRET_KEY",
    }
)


def validate_env(env: dict[str, str] | None) -> dict[str, str] | None:
    """Validate an explicit env override map for blocked keys."""
    if env is None:
        return None
    blocked = _DANGEROUS_ENV_VARS & env.keys()
    if blocked:
        msg = f"Blocked env vars: {', '.join(sorted(blocked))}"
        raise ValueError(msg)
    return env


def resolve_env(env: dict[str, str] | None) -> dict[str, str]:
    """Return subprocess env with dangerous inherited variables removed."""
    safe_env = validate_env(env)
    if safe_env is not None:
        return safe_env
    return {k: v for k, v in os.environ.items() if k not in _DANGEROUS_ENV_VARS}
