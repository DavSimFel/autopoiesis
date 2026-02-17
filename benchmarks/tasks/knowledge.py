"""Benchmark: Knowledge retrieval accuracy.

Tests whether the model can extract and reason about information
from provided context — simulating knowledge file retrieval.
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, system_message

KNOWLEDGE_SAMPLES = [
    Sample(
        input=(
            "Based on the following knowledge file content, answer the question.\n\n"
            "--- knowledge: project-config.md ---\n"
            "# Project Configuration\n"
            "- Runtime: Python 3.12\n"
            "- Package manager: uv\n"
            "- Test framework: pytest\n"
            "- Linter: ruff\n"
            "- Type checker: pyright\n"
            "---\n\n"
            "Question: What type checker does this project use?\n"
            "Answer with just the tool name."
        ),
        target="pyright",
    ),
    Sample(
        input=(
            "Based on the following knowledge file content, answer the question.\n\n"
            "--- knowledge: team-contacts.md ---\n"
            "# Team\n"
            "- Alice: backend lead, alice@example.com\n"
            "- Bob: frontend lead, bob@example.com\n"
            "- Carol: DevOps, carol@example.com\n"
            "---\n\n"
            "Question: Who is responsible for DevOps?\n"
            "Answer with just the person's name."
        ),
        target="Carol",
    ),
    Sample(
        input=(
            "Based on the following knowledge file content, answer the question.\n\n"
            "--- knowledge: deployment.md ---\n"
            "# Deployment\n"
            "- Staging URL: https://staging.example.com\n"
            "- Production URL: https://app.example.com\n"
            "- Deploy tool: GitHub Actions\n"
            "- Rollback: automatic on health check failure\n"
            "---\n\n"
            "Question: What is the production URL?\n"
            "Answer with just the URL."
        ),
        target="https://app.example.com",
    ),
]

SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer questions based on the provided "
    "knowledge file content. Be concise — answer with just the requested information."
)


@task
def knowledge_retrieval() -> Task:
    """Evaluate whether the model can extract facts from knowledge file content."""
    return Task(
        dataset=KNOWLEDGE_SAMPLES,
        solver=[system_message(SYSTEM_PROMPT), generate()],
        scorer=includes(),
    )
