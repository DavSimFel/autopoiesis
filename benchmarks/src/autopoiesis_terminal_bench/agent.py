"""Harbor agent adapter for autopoiesis.

This module implements the BaseInstalledAgent interface to run
autopoiesis in Terminal-Bench evaluations via Harbor.
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

from harbor.agents.installed.base import BaseInstalledAgent, ExecInput
from harbor.models.agent.context import AgentContext
from harbor.models.trial.paths import EnvironmentPaths

# Keys forwarded from host environment into the container.
_FORWARDED_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
)

# Path where autopoiesis is installed inside the container.
_AGENT_ROOT = Path("/installed-agent/autopoiesis")

# Batch result file written by ``python chat.py run --output``.
_RESULT_FILENAME = "batch-result.json"


class AutopoiesisAgent(BaseInstalledAgent):
    """Harbor agent adapter for the autopoiesis coding agent.

    Autopoiesis is installed via git clone + uv and invoked through
    its batch-mode CLI (``python chat.py run``).
    """

    @staticmethod
    def name() -> str:
        return "autopoiesis"

    @property
    def _install_agent_template_path(self) -> Path:
        return Path(__file__).parent / "install-autopoiesis.sh.j2"

    def create_run_agent_commands(self, instruction: str) -> list[ExecInput]:
        """Build CLI invocation for a single benchmark task."""
        escaped = shlex.quote(instruction)
        output_file = EnvironmentPaths.agent_dir / _RESULT_FILENAME

        env = _collect_env()

        activate = f"source {_AGENT_ROOT}/.venv/bin/activate"
        run_cmd = (
            f"cd {_AGENT_ROOT} && {activate} && "
            f"python chat.py run "
            f"--task {escaped} "
            f"--output {output_file} "
            f"--timeout 300"
        )

        return [
            ExecInput(
                command=f"mkdir -p {EnvironmentPaths.agent_dir}",
                env=env,
            ),
            ExecInput(
                command=f"bash -lc {shlex.quote(run_cmd)}",
                env=env,
                timeout_sec=360,
            ),
        ]

    def populate_context_post_run(self, context: AgentContext) -> None:
        """Extract metrics from the batch result JSON."""
        result_file = self.logs_dir / _RESULT_FILENAME

        if not result_file.exists():
            print(f"autopoiesis result file not found: {result_file}")
            return

        data = _load_result(result_file)
        if data is None:
            return

        elapsed = data.get("elapsed_seconds")
        context.metadata = {
            "success": data.get("success", False),
            "approval_rounds": data.get("approval_rounds", 0),
            **({"elapsed_seconds": elapsed} if elapsed is not None else {}),
        }


def _collect_env() -> dict[str, str]:
    """Gather environment variables to forward into the container."""
    env: dict[str, str] = {}
    for key in _FORWARDED_ENV_KEYS:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    return env


def _load_result(path: Path) -> dict[str, object] | None:
    """Parse the batch result JSON, returning *None* on failure."""
    try:
        text = path.read_text(encoding="utf-8")
        result: dict[str, object] = json.loads(text)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to parse result file {path}: {exc}")
        return None
    return result
