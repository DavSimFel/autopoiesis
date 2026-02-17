"""Benchmark: Tool use accuracy.

Tests whether the model selects the correct tool for a given task description.
This is a foundation benchmark — it tests tool selection reasoning, not actual
tool execution against autopoiesis internals.
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import choice
from inspect_ai.solver import multiple_choice

TOOL_USE_SAMPLES = [
    Sample(
        input=(
            "A user asks: 'Search my knowledge base for notes about Python decorators.'\n"
            "Which tool should be used?\n"
            "A) exec_command — run a shell command\n"
            "B) knowledge_search — search the knowledge store\n"
            "C) memory_store — save to long-term memory\n"
            "D) file_write — write a file to disk"
        ),
        target="B",
    ),
    Sample(
        input=(
            "A user asks: 'Remember that my preferred timezone is UTC+1.'\n"
            "Which tool should be used?\n"
            "A) exec_command — run a shell command\n"
            "B) knowledge_search — search the knowledge store\n"
            "C) memory_store — save to long-term memory\n"
            "D) topic_subscribe — subscribe to a topic"
        ),
        target="C",
    ),
    Sample(
        input=(
            "A user asks: 'Run pytest on the current project.'\n"
            "Which tool should be used?\n"
            "A) exec_command — run a shell command\n"
            "B) knowledge_search — search the knowledge store\n"
            "C) memory_store — save to long-term memory\n"
            "D) file_read — read a file from disk"
        ),
        target="A",
    ),
    Sample(
        input=(
            "A user asks: 'Subscribe to updates about deployment status.'\n"
            "Which tool should be used?\n"
            "A) exec_command — run a shell command\n"
            "B) file_write — write a file to disk\n"
            "C) memory_store — save to long-term memory\n"
            "D) topic_subscribe — subscribe to a topic"
        ),
        target="D",
    ),
]


@task
def tool_use_accuracy() -> Task:
    """Evaluate whether the model picks the right tool for a given user request."""
    return Task(
        dataset=TOOL_USE_SAMPLES,
        solver=multiple_choice(),
        scorer=choice(),
    )
