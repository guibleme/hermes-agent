from __future__ import annotations

import threading
from types import SimpleNamespace

from tui_gateway import server


class _Transport:
    observer_surface = "desktop"

    def __init__(self) -> None:
        self.frames: list[dict] = []
        self.written = threading.Event()

    def write(self, obj: dict) -> bool:
        self.frames.append(obj)
        self.written.set()
        return True

    def close(self) -> None:
        return None


def test_inline_rpc_observation_is_metadata_only(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda name, **payload: captured.append((name, payload)) or [],
    )
    monkeypatch.setitem(
        server._methods,
        "test.observed",
        lambda rid, params: server._ok(rid, {"echo": params.get("private_prompt")}),
    )
    transport = _Transport()

    response = server.dispatch(
        {
            "id": "r1",
            "method": "test.observed",
            "params": {
                "session_id": "session-123",
                "private_prompt": "must never enter telemetry",
            },
        },
        transport,
    )

    assert response == {
        "jsonrpc": "2.0",
        "id": "r1",
        "result": {"echo": "must never enter telemetry"},
    }
    assert captured[0][0] == "gateway_rpc"
    payload = captured[0][1]
    assert payload["rpc_method"] == "test.observed"
    assert payload["surface"] == "desktop"
    assert payload["session_id"] == "session-123"
    assert payload["status"] == "ok"
    assert payload["duration_ms"] >= 0
    assert "must never enter telemetry" not in repr(captured)


def test_unknown_method_does_not_persist_untrusted_method_text(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda name, **payload: captured.append((name, payload)) or [],
    )

    response = server.dispatch(
        {"id": "r2", "method": "private user text", "params": {}},
        _Transport(),
    )

    assert response["error"]["code"] == -32601
    assert captured[0][1]["rpc_method"] == "unknown"
    assert captured[0][1]["status"] == "error"
    assert captured[0][1]["error_type"] == "rpc_-32601"
    assert "private user text" not in repr(captured)


def test_long_rpc_observation_completes_in_worker(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda name, **payload: captured.append((name, payload)) or [],
    )
    monkeypatch.setitem(
        server._methods,
        "test.observed.long",
        lambda rid, params: server._ok(rid, {"done": True}),
    )
    monkeypatch.setattr(server, "_LONG_HANDLERS", server._LONG_HANDLERS | {"test.observed.long"})
    transport = _Transport()

    assert server.dispatch(
        {"id": "r3", "method": "test.observed.long", "params": {}},
        transport,
    ) is None
    assert transport.written.wait(timeout=2)
    assert transport.frames[0]["result"] == {"done": True}
    assert captured[0][1]["rpc_method"] == "test.observed.long"
    assert captured[0][1]["status"] == "ok"


def test_connection_observation_omits_peer_and_content(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda name, **payload: captured.append((name, payload)) or [],
    )

    server.observe_gateway_connection(
        surface="dashboard",
        status="closed",
        duration_ms=12.5,
        reason_code="client_disconnect",
        message_count=3,
        parse_errors=1,
        dispatch_crashes=0,
        send_failures=0,
    )

    assert captured == [
        (
            "gateway_connection",
            {
                "platform": "dashboard",
                "surface": "dashboard",
                "status": "closed",
                "reason_code": "client_disconnect",
                "duration_ms": 12.5,
                "message_count": 3,
                "parse_errors": 1,
                "dispatch_crashes": 0,
                "send_failures": 0,
            },
        )
    ]
