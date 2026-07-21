from __future__ import annotations

from types import SimpleNamespace

import pytest

from run_agent import AIAgent


def _agent() -> SimpleNamespace:
    return SimpleNamespace(
        session_id="session-1",
        platform="telegram",
        model="model-1",
        provider="provider-1",
        _last_compaction_in_place=False,
        context_compressor=SimpleNamespace(
            compression_count=0,
            _last_compress_aborted=False,
            _last_compression_made_progress=False,
            _last_summary_fallback_used=False,
            _last_compression_savings_pct=0.0,
            last_compression_rough_tokens=0,
            context_length=128_000,
            threshold_tokens=102_400,
            threshold_percent=0.8,
        ),
    )


def _run(agent, messages, **kwargs):
    return AIAgent._compress_context(agent, messages, "private system prompt", **kwargs)


def test_completed_compression_emits_scalar_metadata(monkeypatch):
    agent = _agent()
    messages = [{"role": "user", "content": "private message"}] * 5
    compressed = [{"role": "user", "content": "private summary"}]
    events = []

    def compress(_agent, _messages, _system, **_kwargs):
        agent.context_compressor.compression_count = 1
        agent.context_compressor._last_compression_made_progress = True
        agent.context_compressor._last_summary_fallback_used = True
        agent.context_compressor._last_compression_savings_pct = 75.5
        agent.context_compressor.last_compression_rough_tokens = 12_000
        agent._last_compaction_in_place = True
        return compressed, "private rebuilt prompt"

    monkeypatch.setattr("agent.conversation_compression.compress_context", compress)
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda name, **payload: events.append((name, payload)),
    )

    result = _run(
        agent,
        messages,
        approx_tokens=120_000,
        task_id="task-1",
        focus_topic="private focus",
        force=True,
    )

    assert result == (compressed, "private rebuilt prompt")
    assert len(events) == 1
    name, payload = events[0]
    assert name == "post_context_compression"
    assert payload["status"] == "completed"
    assert payload["reason_code"] == "compressed"
    assert payload["message_count_before"] == 5
    assert payload["message_count_after"] == 1
    assert payload["approx_tokens_before"] == 120_000
    assert payload["rough_tokens_after"] == 12_000
    assert payload["compression_count"] == 1
    assert payload["in_place"] is True
    assert payload["forced"] is True
    assert payload["used_fallback"] is True
    assert payload["compression_savings_pct"] == 75.5
    assert payload["duration_ms"] >= 0
    encoded = repr(payload)
    assert "private message" not in encoded
    assert "private summary" not in encoded
    assert "private system prompt" not in encoded
    assert "private rebuilt prompt" not in encoded
    assert "private focus" not in encoded


@pytest.mark.parametrize(
    ("aborted", "progress", "expected_status", "expected_reason"),
    [
        (True, False, "aborted", "summary_failure"),
        (False, False, "no_progress", "unchanged"),
    ],
)
def test_non_completed_compression_outcomes_are_truthful(
    monkeypatch, aborted, progress, expected_status, expected_reason
):
    agent = _agent()
    messages = [{"role": "user", "content": "private"}]
    events = []

    def compress(_agent, _messages, _system, **_kwargs):
        agent.context_compressor._last_compress_aborted = aborted
        agent.context_compressor._last_compression_made_progress = progress
        return messages, "private prompt"

    monkeypatch.setattr("agent.conversation_compression.compress_context", compress)
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda name, **payload: events.append((name, payload)),
    )

    assert _run(agent, messages) == (messages, "private prompt")
    assert events[0][1]["status"] == expected_status
    assert events[0][1]["reason_code"] == expected_reason


def test_compression_exception_is_observed_without_masking(monkeypatch):
    agent = _agent()
    events = []
    failure = RuntimeError("private failure detail")

    def compress(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr("agent.conversation_compression.compress_context", compress)
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda name, **payload: events.append((name, payload)),
    )

    with pytest.raises(RuntimeError) as caught:
        _run(agent, [{"role": "user", "content": "private"}])

    assert caught.value is failure
    assert events[0][1]["status"] == "error"
    assert events[0][1]["reason_code"] == "exception"
    assert events[0][1]["error_type"] == "RuntimeError"
    assert "private failure detail" not in repr(events)


def test_observer_failure_does_not_change_compression_result(monkeypatch):
    agent = _agent()
    messages = [{"role": "user", "content": "private"}]
    expected = (messages, "private prompt")

    monkeypatch.setattr(
        "agent.conversation_compression.compress_context",
        lambda *_args, **_kwargs: expected,
    )
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("observer down")),
    )

    assert _run(agent, messages) is expected
