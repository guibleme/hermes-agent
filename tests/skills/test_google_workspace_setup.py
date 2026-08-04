from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "productivity"
    / "google-workspace"
    / "scripts"
    / "setup.py"
)


def load_setup_module():
    spec = importlib.util.spec_from_file_location("google_workspace_setup", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readonly_service_selection_excludes_write_scopes():
    setup = load_setup_module()

    services = setup._normalize_services("email,calendar")
    scopes = setup._scopes_for(services, "readonly")

    assert services == ["email", "calendar"]
    assert scopes == [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
    ]
    assert all("send" not in scope and "modify" not in scope for scope in scopes)


def test_token_metadata_controls_scope_completeness():
    setup = load_setup_module()
    payload = {
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/calendar.readonly",
        ],
        "hermes_services": ["email", "calendar"],
        "hermes_access": "readonly",
    }

    assert setup._missing_scopes_from_payload(payload) == []


def test_unknown_service_is_rejected():
    setup = load_setup_module()

    try:
        setup._normalize_services("calendar,made-up")
    except ValueError as error:
        assert "made-up" in str(error)
    else:
        raise AssertionError("unknown Google Workspace service was accepted")
