"""Tests for interactive approval collection helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

import chat_approval


def _input_feeder(values: list[str], prompts: list[str] | None = None) -> Callable[[str], str]:
    iterator = iter(values)
    capture = prompts if prompts is not None else []

    def _fake_input(prompt: str) -> str:
        capture.append(prompt)
        try:
            return next(iterator)
        except StopIteration as exc:
            raise AssertionError("Input requested more times than expected.") from exc

    return _fake_input


def _eof_raiser(_prompt: str) -> str:
    raise EOFError


def _request(tool_call_id: str, tool_name: str) -> dict[str, Any]:
    return {"tool_call_id": tool_call_id, "tool_name": tool_name, "args": {}}


# -- _collect_single_decision via gather_approvals ---------------------------


def _make_payload(requests: list[dict[str, Any]], nonce: str = "n1") -> dict[str, Any]:
    return {"nonce": nonce, "plan_hash_prefix": "abcd1234", "requests": requests}


class _FakeApprovalStore:
    """Minimal stub that records store_signed_approval calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def store_signed_approval(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class _FakeKeyManager:
    pass


def _gather(payload: dict[str, Any]) -> str:
    store = _FakeApprovalStore()
    result = chat_approval.gather_approvals(
        payload,
        approval_store=store,  # type: ignore[arg-type]
        key_manager=_FakeKeyManager(),  # type: ignore[arg-type]
    )
    return result


# -- Happy-path tests -------------------------------------------------------


class TestSingleDecision:
    def test_approve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", _input_feeder(["y"]))
        payload = _make_payload([_request("c1", "run")])

        result = json.loads(_gather(payload))
        assert result["decisions"][0]["approved"] is True
        assert result["decisions"][0]["denial_message"] is None

    def test_deny_with_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prompts: list[str] = []
        monkeypatch.setattr("builtins.input", _input_feeder(["n", "Too risky"], prompts))
        payload = _make_payload([_request("c1", "write_file")])

        result = json.loads(_gather(payload))
        assert result["decisions"][0]["approved"] is False
        assert result["decisions"][0]["denial_message"] == "Too risky"
        assert prompts == ["  Approve? [Y/n] ", "  Denial reason (optional): "]

    def test_deny_empty_reason_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", _input_feeder(["n", ""]))
        payload = _make_payload([_request("c1", "write_file")])

        result = json.loads(_gather(payload))
        assert result["decisions"][0]["denial_message"] == "User denied this action."

    def test_eof_denies_without_reason_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", _eof_raiser)
        payload = _make_payload([_request("c1", "run")])

        result = json.loads(_gather(payload))
        assert result["decisions"][0]["approved"] is False
        assert result["decisions"][0]["denial_message"] == "User denied this action."

    def test_unrecognized_input_denies_with_reason(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("builtins.input", _input_feeder(["maybe", "Changed my mind"]))
        payload = _make_payload([_request("c1", "run")])

        result = json.loads(_gather(payload))
        assert result["decisions"][0]["approved"] is False
        assert result["decisions"][0]["denial_message"] == "Changed my mind"


class TestBatchDecisions:
    def test_approve_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", _input_feeder(["y"]))
        reqs = [_request("c1", "run"), _request("c2", "exec")]
        payload = _make_payload(reqs)

        result = json.loads(_gather(payload))
        assert all(d["approved"] is True for d in result["decisions"])

    def test_deny_all_with_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prompts: list[str] = []
        monkeypatch.setattr("builtins.input", _input_feeder(["n", "Dangerous"], prompts))
        reqs = [_request("c1", "write_file"), _request("c2", "exec")]
        payload = _make_payload(reqs)

        result = json.loads(_gather(payload))
        assert all(d["approved"] is False for d in result["decisions"])
        assert all(d["denial_message"] == "Dangerous" for d in result["decisions"])

    def test_pick_per_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "builtins.input",
            _input_feeder(["pick", "n", "No writes", "y"]),
        )
        reqs = [_request("c1", "write_file"), _request("c2", "read_file")]
        payload = _make_payload(reqs)

        result = json.loads(_gather(payload))
        assert result["decisions"][0]["approved"] is False
        assert result["decisions"][0]["denial_message"] == "No writes"
        assert result["decisions"][1]["approved"] is True

    def test_eof_denies_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", _eof_raiser)
        reqs = [_request("c1", "run"), _request("c2", "exec")]
        payload = _make_payload(reqs)

        result = json.loads(_gather(payload))
        assert all(d["approved"] is False for d in result["decisions"])

    def test_unrecognized_input_denies_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", _input_feeder(["wat", "Nope"]))
        reqs = [_request("c1", "run"), _request("c2", "exec")]
        payload = _make_payload(reqs)

        result = json.loads(_gather(payload))
        assert all(d["approved"] is False for d in result["decisions"])
        assert all(d["denial_message"] == "Nope" for d in result["decisions"])

    def test_pick_eof_on_individual(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responses = iter(["pick", "y"])

        def _eof_after_first(_prompt: str) -> str:
            try:
                return next(responses)
            except StopIteration:
                raise EOFError from None

        monkeypatch.setattr("builtins.input", _eof_after_first)
        reqs = [_request("c1", "run"), _request("c2", "exec")]
        payload = _make_payload(reqs)

        result = json.loads(_gather(payload))
        assert result["decisions"][0]["approved"] is True
        assert result["decisions"][1]["approved"] is False


class TestDeserializeConsistency:
    """Ensure deserialize uses the same default denial message."""

    def test_missing_denial_message_uses_default(self) -> None:


        store = MagicMock()
        store.verify_and_consume.return_value = [
            {"tool_call_id": "c1", "approved": False, "denial_message": None},
        ]
        km = MagicMock()
        scope = MagicMock()

        results = chat_approval.deserialize_deferred_results(
            "{}",
            scope=scope,
            approval_store=store,
            key_manager=km,
        )
        denied = results.approvals["c1"]
        assert isinstance(denied, chat_approval.ToolDenied)
        assert denied.message == "User denied this action."
