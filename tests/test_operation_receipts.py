"""Durable client-mutation receipt behavior."""

import threading

from hermes_state import SessionDB


def _claim(db: SessionDB, *, result: dict | None = None):
    return db.claim_operation_receipt(
        "op-1234567890abcdef",
        kind="session.create",
        request_hash="a" * 64,
        session_key="session-stable",
        state="creating",
        claim_token="claim-a",
        owner_boot_id="boot-a",
        result=result,
    )


def test_operation_receipt_survives_reopen(tmp_path):
    path = tmp_path / "state.db"
    first = SessionDB(db_path=path)
    created, receipt = _claim(first, result={"stored_session_id": "session-stable"})
    assert created is True
    assert receipt["result"] == {"stored_session_id": "session-stable"}
    first.close()

    reopened = SessionDB(db_path=path)
    try:
        created, replay = _claim(
            reopened,
            result={"stored_session_id": "unused-loser"},
        )
        assert created is False
        assert replay["session_key"] == "session-stable"
        assert replay["result"] == {"stored_session_id": "session-stable"}
    finally:
        reopened.close()


def test_operation_receipt_claim_serializes_across_connections(tmp_path):
    path = tmp_path / "state.db"
    first = SessionDB(db_path=path)
    second = SessionDB(db_path=path)
    barrier = threading.Barrier(2)
    outcomes: list[tuple[bool, dict]] = []

    def claim(db: SessionDB, token: str, stored_id: str) -> None:
        barrier.wait()
        outcomes.append(
            db.claim_operation_receipt(
                "op-concurrent-123456",
                kind="session.create",
                request_hash="b" * 64,
                session_key=stored_id,
                state="creating",
                claim_token=token,
                owner_boot_id="boot-a",
                result={"stored_session_id": stored_id},
            )
        )

    threads = [
        threading.Thread(target=claim, args=(first, "claim-a", "session-a")),
        threading.Thread(target=claim, args=(second, "claim-b", "session-b")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    try:
        assert all(not thread.is_alive() for thread in threads)
        assert sorted(created for created, _receipt in outcomes) == [False, True]
        assert len({receipt["session_key"] for _created, receipt in outcomes}) == 1
    finally:
        first.close()
        second.close()


def test_operation_receipt_finish_is_claim_token_guarded(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        _claim(db)
        assert (
            db.finish_operation_receipt(
                "op-1234567890abcdef",
                claim_token="wrong-claim",
                state="completed",
                result={"status": "complete"},
            )
            is False
        )
        assert (
            db.finish_operation_receipt(
                "op-1234567890abcdef",
                claim_token="claim-a",
                state="completed",
                result={"status": "complete"},
            )
            is True
        )
        receipt = db.get_operation_receipt("op-1234567890abcdef")
        assert receipt is not None
        assert receipt["state"] == "completed"
        assert receipt["result"] == {"status": "complete"}
        assert receipt["completed_at"] is not None
    finally:
        db.close()
