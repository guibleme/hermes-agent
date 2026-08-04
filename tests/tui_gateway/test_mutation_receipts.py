"""Content-bound mutation receipts for the TUI/Desktop gateway."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from hermes_state import SessionDB
from tui_gateway import server


class _ImmediateThread:
    def __init__(self, target=None, *args, **kwargs):
        self._target = target

    def start(self):
        self._target()


@pytest.fixture()
def receipt_server(monkeypatch, tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    server._sessions.clear()
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(
        server,
        "_claim_active_session_slot",
        lambda *args, **kwargs: (None, None),
    )
    monkeypatch.setattr(server, "_schedule_agent_build", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        server,
        "_schedule_session_cap_enforcement",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(server, "_completion_cwd", lambda _params=None: str(tmp_path))
    yield db
    server._sessions.clear()
    db.close()


def _create_params(key: str, **overrides):
    params = {
        "cols": 80,
        "idempotency_key": key,
        "source": "desktop",
        "title": "Prepared operation",
    }
    params.update(overrides)
    return params


def test_session_create_replay_returns_one_logical_session(receipt_server):
    params = _create_params("create-1234567890abcdef")

    first = server._methods["session.create"]("r1", params)["result"]
    second = server._methods["session.create"]("r2", params)["result"]

    assert first["stored_session_id"] == second["stored_session_id"]
    assert first["session_id"] == second["session_id"]
    assert len(server._sessions) == 1
    assert first["receipt"]["replayed"] is False
    assert second["receipt"]["replayed"] is True
    assert first["info"]["mutation_receipt_contract"] == 1


def test_session_create_conflict_does_not_allocate_another_session(receipt_server):
    key = "create-conflict-123456"
    first = server._methods["session.create"]("r1", _create_params(key))
    conflict = server._methods["session.create"](
        "r2",
        _create_params(key, title="Different operation"),
    )

    assert "result" in first
    assert conflict["error"]["code"] == 4091
    assert len(server._sessions) == 1


def test_session_create_reconstructs_same_stored_identity_after_restart(
    receipt_server,
):
    params = _create_params("create-restart-1234567")
    first = server._methods["session.create"]("r1", params)["result"]
    server._sessions.clear()

    second = server._methods["session.create"]("r2", params)["result"]

    assert second["stored_session_id"] == first["stored_session_id"]
    assert len(server._sessions) == 1
    assert second["receipt"]["replayed"] is True


def test_session_create_receipt_is_owned_by_selected_profile(
    receipt_server,
    monkeypatch,
    tmp_path,
):
    profile_home = tmp_path / "profiles" / "secondary"
    profile_home.mkdir(parents=True)
    monkeypatch.setattr(
        server,
        "_profile_home",
        lambda profile: profile_home if profile == "secondary" else None,
    )
    key = "create-profile-12345678"

    result = server._methods["session.create"](
        "r1",
        _create_params(key, profile="secondary"),
    )

    assert "result" in result
    assert receipt_server.get_operation_receipt(key) is None
    profile_db = SessionDB(db_path=profile_home / "state.db")
    try:
        receipt = profile_db.get_operation_receipt(key)
        assert receipt is not None
        assert receipt["state"] == "completed"
    finally:
        profile_db.close()


def test_idempotent_session_create_fails_closed_without_state_db(
    receipt_server,
    monkeypatch,
):
    monkeypatch.setattr(server, "_get_db", lambda: None)

    result = server._methods["session.create"](
        "r1",
        _create_params("create-no-database-1234"),
    )

    assert result["error"]["code"] == 5037
    assert server._sessions == {}


def test_prompt_submit_replay_dispatches_once(receipt_server, monkeypatch):
    created = server._methods["session.create"](
        "r1",
        _create_params("create-for-prompt-123456"),
    )["result"]
    sid = created["session_id"]
    session = server._sessions[sid]
    dispatched = threading.Event()
    calls = []

    def build(_sid, record):
        record["agent"] = object()
        record["agent_ready"].set()

    def run_prompt(_rid, _sid, _record, prompt, **kwargs):
        calls.append((prompt, kwargs.get("operation_receipt")))
        dispatched.set()

    monkeypatch.setattr(server, "_start_agent_build", build)
    monkeypatch.setattr(server, "_run_prompt_submit", run_prompt)
    monkeypatch.setattr(
        server,
        "_load_dashboard_process_isolation_config",
        lambda: {},
    )
    monkeypatch.setattr(
        server,
        "_session_uses_compute_host",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(server, "_ensure_session_db_row", lambda _session: None)
    monkeypatch.setattr(server, "_persist_branch_seed", lambda _session: None)

    params = {
        "idempotency_key": "prompt-1234567890abcdef",
        "session_id": sid,
        "stored_session_id": created["stored_session_id"],
        "text": "Continue the reviewed operation",
    }
    first = server._methods["prompt.submit"]("p1", params)["result"]
    assert dispatched.wait(timeout=2)
    second = server._methods["prompt.submit"]("p2", params)["result"]

    assert len(calls) == 1
    assert first["receipt"]["replayed"] is False
    assert second["receipt"]["replayed"] is True
    assert second["status"] == "streaming"


def test_concurrent_prompt_retries_replay_one_claim(receipt_server, monkeypatch):
    created = server._methods["session.create"](
        "r1",
        _create_params("create-concurrent-123456"),
    )["result"]
    sid = created["session_id"]
    session = server._sessions[sid]
    session["agent"] = object()
    session["agent_ready"].set()
    barrier = threading.Barrier(2)
    local = threading.local()
    original_get = receipt_server.get_operation_receipt

    def synchronized_get(operation_id):
        receipt = original_get(operation_id)
        if operation_id == "prompt-concurrent-123456" and not getattr(
            local, "did_wait", False
        ):
            local.did_wait = True
            barrier.wait(timeout=2)
        return receipt

    monkeypatch.setattr(receipt_server, "get_operation_receipt", synchronized_get)
    monkeypatch.setattr(
        server,
        "_load_dashboard_process_isolation_config",
        lambda: {},
    )
    monkeypatch.setattr(
        server,
        "_session_uses_compute_host",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(server, "_ensure_session_db_row", lambda _session: None)
    monkeypatch.setattr(server, "_persist_branch_seed", lambda _session: None)
    dispatches = []
    monkeypatch.setattr(
        server,
        "_run_prompt_submit",
        lambda *_args, **_kwargs: dispatches.append(1),
    )
    params = {
        "idempotency_key": "prompt-concurrent-123456",
        "session_id": sid,
        "stored_session_id": created["stored_session_id"],
        "text": "Dispatch once under concurrency",
    }

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda rid: server._methods["prompt.submit"](rid, params),
                ("p1", "p2"),
            )
        )

    assert all("result" in response for response in results)
    assert (
        sum(response["result"]["receipt"]["replayed"] is False for response in results)
        == 1
    )
    assert len(dispatches) == 1


def test_prompt_receipt_reaches_terminal_state(receipt_server, monkeypatch):
    created = server._methods["session.create"](
        "r1",
        _create_params("create-terminal-1234567"),
    )["result"]
    sid = created["session_id"]
    calls = []
    completion_receipt_states = []

    class Agent:
        model = "test-model"
        provider = "test-provider"

        def run_conversation(
            self,
            prompt,
            conversation_history=None,
            stream_callback=None,
        ):
            calls.append(prompt)
            return {
                "final_response": "",
                "messages": [{"role": "user", "content": prompt}],
            }

    def build(_sid, record):
        record["agent"] = Agent()
        record["agent_ready"].set()

    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_start_agent_build", build)

    def emit(event, _sid, _payload=None):
        if event == "message.complete":
            receipt = receipt_server.get_operation_receipt(
                "prompt-terminal-123456"
            )
            completion_receipt_states.append(receipt["state"])

    monkeypatch.setattr(server, "_emit", emit)
    monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
    monkeypatch.setattr(server, "render_message", lambda _raw, _cols: None)
    monkeypatch.setattr(
        server,
        "_load_dashboard_process_isolation_config",
        lambda: {},
    )
    monkeypatch.setattr(
        server,
        "_session_uses_compute_host",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(server, "_ensure_session_db_row", lambda _session: None)
    monkeypatch.setattr(server, "_persist_branch_seed", lambda _session: None)

    params = {
        "idempotency_key": "prompt-terminal-123456",
        "session_id": sid,
        "stored_session_id": created["stored_session_id"],
        "text": "Finish once",
    }
    first = server._methods["prompt.submit"]("p1", params)["result"]
    replay = server._methods["prompt.submit"]("p2", params)["result"]

    assert calls == ["Finish once"]
    assert completion_receipt_states == ["completed"]
    assert first["receipt"]["state"] == "running"
    assert replay["receipt"]["state"] == "completed"
    assert replay["status"] == "complete"


def test_prompt_submit_conflict_and_restart_are_fail_closed(
    receipt_server,
    monkeypatch,
):
    created = server._methods["session.create"](
        "r1",
        _create_params("create-fail-closed-1234"),
    )["result"]
    sid = created["session_id"]
    session = server._sessions[sid]
    session["agent"] = object()
    session["agent_ready"].set()
    monkeypatch.setattr(
        server,
        "_load_dashboard_process_isolation_config",
        lambda: {},
    )
    monkeypatch.setattr(
        server,
        "_session_uses_compute_host",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(server, "_ensure_session_db_row", lambda _session: None)
    monkeypatch.setattr(server, "_persist_branch_seed", lambda _session: None)
    dispatched = threading.Event()
    monkeypatch.setattr(
        server,
        "_run_prompt_submit",
        lambda *_args, **_kwargs: dispatched.set(),
    )

    params = {
        "idempotency_key": "prompt-fail-closed-1234",
        "session_id": sid,
        "stored_session_id": created["stored_session_id"],
        "text": "One operation",
    }
    server._methods["prompt.submit"]("p1", params)
    assert dispatched.wait(timeout=2)

    conflict = server._methods["prompt.submit"](
        "p2",
        {**params, "text": "Different operation"},
    )
    assert conflict["error"]["code"] == 4091

    monkeypatch.setattr(server, "_gateway_boot_id", "different-boot")
    server._sessions.clear()
    replay = server._methods["prompt.submit"]("p3", params)["result"]
    assert replay["status"] == "indeterminate"


def test_keyed_prompt_rejects_busy_session_before_claim(
    receipt_server,
    monkeypatch,
):
    created = server._methods["session.create"](
        "r1",
        _create_params("create-busy-123456789"),
    )["result"]
    session = server._sessions[created["session_id"]]
    session["running"] = True
    monkeypatch.setattr(
        server,
        "_load_dashboard_process_isolation_config",
        lambda: {},
    )
    monkeypatch.setattr(
        server,
        "_session_uses_compute_host",
        lambda *_args, **_kwargs: False,
    )

    result = server._methods["prompt.submit"](
        "p1",
        {
            "idempotency_key": "prompt-busy-123456789",
            "session_id": created["session_id"],
            "stored_session_id": created["stored_session_id"],
            "text": "Do not queue this",
        },
    )

    assert result["error"]["code"] == 4030
    assert receipt_server.get_operation_receipt("prompt-busy-123456789") is None


@pytest.mark.parametrize(
    "unsupported",
    [
        {"text": [{"type": "text", "text": "structured"}]},
        {"text": "rewind", "truncate_before_user_ordinal": 0},
        {"text": "barge in", "interrupted": True},
    ],
)
def test_keyed_prompt_rejects_unsupported_shape_before_claim(
    receipt_server,
    unsupported,
):
    operation_id = "prompt-unsupported-1234"
    result = server._methods["prompt.submit"](
        "p1",
        {
            "idempotency_key": operation_id,
            "session_id": "not-needed",
            "stored_session_id": "stable-not-needed",
            **unsupported,
        },
    )

    assert result["error"]["code"] == 4030
    assert receipt_server.get_operation_receipt(operation_id) is None
