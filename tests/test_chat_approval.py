"""Tests for interactive approval collection helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

import chat_approval


def _input_feeder(values: list[str], prompts: list[str]) -> Callable[[str], str]:
    iterator = iter(values)

    def _fake_input(prompt: str) -> str:
        prompts.append(prompt)
        try:
            return next(iterator)
        except StopIteration as exc:
            raise AssertionError("Input requested more times than expected.") from exc

    return _fake_input


def _request(tool_call_id: str, tool_name: str) -> dict[str, Any]:
    return {"tool_call_id": tool_call_id, "tool_name": tool_name, "args": {}}


def testcollect_single_decision_denied_reason_captured(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []
    monkeypatch.setattr(
        "builtins.input",
        _input_feeder(["n", "Needs a safer path"], prompts),
    )

    result = chat_approval.collect_single_decision(_request("call-1", "write_file"))

    assert result == [
        {
            "tool_call_id": "call-1",
            "approved": False,
            "denial_message": "Needs a safer path",
        }
    ]
    assert prompts == ["  Approve? [Y/n] ", "  Denial reason (optional): "]


def testcollect_single_decision_denied_empty_reason_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("builtins.input", _input_feeder(["n", ""], []))

    result = chat_approval.collect_single_decision(_request("call-1", "write_file"))

    assert result == [
        {
            "tool_call_id": "call-1",
            "approved": False,
            "denial_message": "User denied this action.",
        }
    ]


def testcollect_batch_decisions_deny_all_reason_applies_to_each(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    monkeypatch.setattr(
        "builtins.input",
        _input_feeder(["n", "Dangerous command"], prompts),
    )
    requests = [_request("call-1", "write_file"), _request("call-2", "exec")]

    result = chat_approval.collect_batch_decisions(requests)

    assert result == [
        {
            "tool_call_id": "call-1",
            "approved": False,
            "denial_message": "Dangerous command",
        },
        {
            "tool_call_id": "call-2",
            "approved": False,
            "denial_message": "Dangerous command",
        },
    ]
    assert prompts == ["  Approve all? [Y/n/pick] ", "  Denial reason (optional): "]


def testcollect_batch_decisions_pick_captures_reason_per_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    monkeypatch.setattr(
        "builtins.input",
        _input_feeder(["pick", "n", "No filesystem writes", "y"], prompts),
    )
    requests = [_request("call-1", "write_file"), _request("call-2", "read_file")]

    result = chat_approval.collect_batch_decisions(requests)

    assert result == [
        {
            "tool_call_id": "call-1",
            "approved": False,
            "denial_message": "No filesystem writes",
        },
        {
            "tool_call_id": "call-2",
            "approved": True,
            "denial_message": None,
        },
    ]
    assert prompts == [
        "  Approve all? [Y/n/pick] ",
        "  [1] write_file - approve? [Y/n] ",
        "  Denial reason (optional): ",
        "  [2] read_file - approve? [Y/n] ",
    ]
