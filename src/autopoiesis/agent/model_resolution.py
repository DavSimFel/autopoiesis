"""Model/provider resolution helpers for chat runtime."""

from __future__ import annotations

import os

from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

_SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"anthropic", "openrouter"})


def required_env(name: str) -> str:
    """Return env var value or exit with a clear startup error."""
    value = os.getenv(name)
    if value:
        return value
    raise SystemExit(f"Missing required environment variable: {name}")


def detect_provider_from_model(model_name: str) -> str | None:
    """Detect provider from a model identifier when it is unambiguous."""
    normalized = model_name.strip().lower()
    if normalized.startswith("anthropic:"):
        return "anthropic"
    return None


def resolve_provider(provider: str | None = None) -> str:
    """Resolve and validate AI provider selection.

    When provider is omitted, reads ``AI_PROVIDER`` and defaults to
    ``anthropic`` for backwards-compatible startup behavior.
    """
    raw = provider if provider is not None else os.getenv("AI_PROVIDER", "anthropic")
    normalized = raw.strip().lower()
    if not normalized:
        return "anthropic"
    if normalized in _SUPPORTED_PROVIDERS:
        return normalized

    detected = detect_provider_from_model(normalized)
    if detected is not None:
        return detected
    raise SystemExit("Unsupported AI_PROVIDER. Use 'openrouter' or 'anthropic'.")


def build_model_settings() -> ModelSettings | None:
    """Build ModelSettings from AI_TEMPERATURE, AI_MAX_TOKENS, AI_TOP_P env vars."""
    settings: ModelSettings = {}

    temp_raw = os.getenv("AI_TEMPERATURE")
    if temp_raw is not None:
        settings["temperature"] = float(temp_raw)

    max_tokens_raw = os.getenv("AI_MAX_TOKENS")
    if max_tokens_raw is not None:
        settings["max_tokens"] = int(max_tokens_raw)

    top_p_raw = os.getenv("AI_TOP_P")
    if top_p_raw is not None:
        settings["top_p"] = float(top_p_raw)

    return settings if settings else None


def _build_anthropic_model() -> str:
    """Build Anthropic model string. Requires ANTHROPIC_API_KEY."""
    required_env("ANTHROPIC_API_KEY")
    return os.getenv("ANTHROPIC_MODEL", "anthropic:claude-3-5-sonnet-latest")


def _build_openrouter_model() -> OpenAIChatModel:
    """Build OpenRouter model instance. Requires OPENROUTER_API_KEY."""
    return OpenAIChatModel(
        os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        provider=OpenAIProvider(
            base_url="https://openrouter.ai/api/v1",
            api_key=required_env("OPENROUTER_API_KEY"),
        ),
    )


def resolve_model(provider: str | None = None) -> Model | str:
    """Resolve primary model with optional fallback for provider resilience."""
    selected_provider = resolve_provider(provider)
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    has_openrouter = bool(os.getenv("OPENROUTER_API_KEY"))

    if selected_provider == "anthropic":
        primary: Model | str = _build_anthropic_model()
        if has_openrouter:
            return FallbackModel(primary, _build_openrouter_model())
        return primary

    primary = _build_openrouter_model()
    if has_anthropic:
        return FallbackModel(primary, _build_anthropic_model())
    return primary


def resolve_model_from_config(model_id: str) -> Model | str:
    """Resolve a pydantic_ai Model from an ``AgentConfig`` model identifier.

    Accepts ``"provider/model-name"`` format (e.g. ``"anthropic/claude-sonnet-4"``)
    and converts it to the appropriate pydantic_ai model, checking for required
    API keys.  Falls back to treating the string as a raw pydantic_ai model
    identifier when no known provider prefix is found.

    Examples::

        resolve_model_from_config("anthropic/claude-sonnet-4")
        # → "anthropic:claude-sonnet-4"  (requires ANTHROPIC_API_KEY)

        resolve_model_from_config("openrouter/openai/gpt-4o-mini")
        # → OpenAIChatModel(...)         (requires OPENROUTER_API_KEY)

        resolve_model_from_config("anthropic:claude-3-5-sonnet-latest")
        # → "anthropic:claude-3-5-sonnet-latest"  (pass-through)
    """
    if "/" not in model_id:
        # No slash → treat as a raw pydantic_ai model string and return as-is.
        return model_id

    prefix, model_name = model_id.split("/", 1)
    provider = prefix.strip().lower()

    if provider == "anthropic":
        required_env("ANTHROPIC_API_KEY")
        return f"anthropic:{model_name}"

    if provider == "openrouter":
        api_key = required_env("OPENROUTER_API_KEY")
        return OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
            ),
        )

    # Unknown provider — pass through as-is and let pydantic_ai handle it.
    return model_id
