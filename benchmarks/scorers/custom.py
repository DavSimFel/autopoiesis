"""Custom scorers implementing the evaluation mode taxonomy.

Modes: exact | contains | llm_judge | metric_threshold
Reference: docs/research/agent-benchmarking-strategy.md
"""

from inspect_ai.scorer import (
    Score,
    Target,
    accuracy,
    scorer,
)
from inspect_ai.solver import TaskState


@scorer(metrics=[accuracy()])
def exact_match() -> object:
    """Score by exact string equality against the target."""

    async def score(state: TaskState, target: Target) -> Score:
        answer = state.output.completion.strip() if state.output else ""
        expected = target.text.strip()
        return Score(
            value="C" if answer == expected else "I",
            answer=answer,
            explanation=f"Expected: {expected!r}, Got: {answer!r}",
        )

    return score


@scorer(metrics=[accuracy()])
def contains_match() -> object:
    """Score by substring presence in the model output."""

    async def score(state: TaskState, target: Target) -> Score:
        answer = state.output.completion if state.output else ""
        expected = target.text
        found = expected.lower() in answer.lower()
        return Score(
            value="C" if found else "I",
            answer=answer,
            explanation=f"Looking for {expected!r} in output (found={found})",
        )

    return score


@scorer(metrics=[accuracy()])
def metric_threshold(threshold: float = 0.8) -> object:
    """Score by checking if a numeric value in the output meets a threshold.

    Expects the model output to contain a parseable float.
    """

    async def score(state: TaskState, target: Target) -> Score:
        answer = state.output.completion.strip() if state.output else ""
        try:
            value = float(answer)
        except ValueError:
            return Score(
                value="I",
                answer=answer,
                explanation=f"Could not parse {answer!r} as float",
            )
        passed = value >= threshold
        return Score(
            value="C" if passed else "I",
            answer=answer,
            explanation=f"Value {value} {'≥' if passed else '<'} threshold {threshold}",
        )

    return score
