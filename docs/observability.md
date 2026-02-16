# Observability

Autopoiesis supports distributed tracing via [OpenTelemetry](https://opentelemetry.io/)
and ships a ready-to-use [SigNoz](https://signoz.io/) stack for local development.

## Quick Start

### 1. Start SigNoz

```bash
docker compose -f docker/docker-compose.signoz.yml up -d
```

SigNoz UI: **<http://localhost:3301>**

### 2. Enable Tracing

Set these environment variables (or add to `.env`):

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=autopoiesis
```

Then start autopoiesis normally. Traces are exported automatically.

### 3. Stop SigNoz

```bash
docker compose -f docker/docker-compose.signoz.yml down
```

Add `-v` to also remove stored trace data.

## What Gets Traced

### Resource Attributes

Every span includes:

| Attribute | Source |
|-----------|--------|
| `service.name` | `OTEL_SERVICE_NAME` env var |
| `autopoiesis.agent.name` | `DBOS_AGENT_NAME` env var |
| `autopoiesis.provider` | `AI_PROVIDER` env var |
| `autopoiesis.model.name` | Active model from env config |

### Spans

| Span Name | Description | Custom Attributes |
|-----------|-------------|-------------------|
| `agent.run` | One work-item execution | `model_name`, `provider`, `workflow_id` |

## Architecture

```
autopoiesis ──OTLP/gRPC:4317──▸ otel-collector ──▸ clickhouse
                                                        │
                                         query-service ◂─┘
                                              │
                                          frontend:3301
```

## Troubleshooting

- **No traces appearing?** Check that `OTEL_EXPORTER_OTLP_ENDPOINT` is set
  and SigNoz is running (`docker compose -f docker/docker-compose.signoz.yml ps`).
- **Port conflicts?** The stack uses 3301 (UI), 4317 (gRPC), 4318 (HTTP).
  Adjust in `docker-compose.signoz.yml` if needed.
- **Missing OTEL packages?** Install with
  `uv add opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc`.
