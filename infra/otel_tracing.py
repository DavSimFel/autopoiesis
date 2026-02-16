"""OpenTelemetry tracing helpers for autopoiesis.

Configures the OTEL SDK when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set and
exposes a module-level tracer for manual span instrumentation.

Dependencies: (stdlib only, optional opentelemetry)
Wired in: agent/worker.py → run_agent_step()
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from types import ModuleType
from typing import Any

_log = logging.getLogger(__name__)

TRACER_NAME = "autopoiesis"
_SERVICE_NAME_DEFAULT = "autopoiesis"


def _import_trace() -> ModuleType | None:
    """Return the opentelemetry.trace module if available."""
    try:
        from opentelemetry import trace as _t

        return _t
    except ModuleNotFoundError:
        return None


def _try_configure_sdk() -> None:
    """Bootstrap the OTEL SDK if the exporter endpoint is configured."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return

    trace_mod = _import_trace()
    if trace_mod is None:
        _log.warning(
            "opentelemetry packages not installed — tracing disabled. "
            "Install with: uv add opentelemetry-api opentelemetry-sdk "
            "opentelemetry-exporter-otlp-proto-grpc"
        )
        return

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ModuleNotFoundError:
        _log.warning("opentelemetry SDK/exporter packages missing — tracing disabled.")
        return

    service_name = os.getenv("OTEL_SERVICE_NAME", _SERVICE_NAME_DEFAULT)
    agent_name = os.getenv("DBOS_AGENT_NAME", "chat")
    provider_name = os.getenv("AI_PROVIDER", "unknown")
    model_name = os.getenv("ANTHROPIC_MODEL") or os.getenv("OPENROUTER_MODEL") or "unknown"

    resource = Resource.create(
        {
            "service.name": service_name,
            "autopoiesis.agent.name": agent_name,
            "autopoiesis.provider": provider_name,
            "autopoiesis.model.name": model_name,
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    # Respect standard OTEL env var; default insecure for local dev.
    insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() == "true"
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=insecure)
    tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    trace_mod.set_tracer_provider(tracer_provider)
    _log.info("OTEL tracing enabled → %s (service=%s)", endpoint, service_name)


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, str | int | float | bool] | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Context manager that opens a span if OTEL is available, else no-ops.

    Yields a mutable dict; callers can add ``result_attributes`` that are
    set on the span before it closes.
    """
    result_attrs: dict[str, Any] = {}
    trace_mod = _import_trace()
    if trace_mod is None:
        yield result_attrs
        return

    tracer = trace_mod.get_tracer(TRACER_NAME)
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield result_attrs
        for key, value in result_attrs.items():
            span.set_attribute(key, value)


def configure() -> None:
    """One-shot SDK bootstrap — safe to call multiple times."""
    _try_configure_sdk()
