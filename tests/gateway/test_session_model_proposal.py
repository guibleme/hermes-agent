"""Conversation-boundary contract for plugin-proposed model lanes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import ChannelOverride, GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource


def _source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="user-1",
        chat_id="chat-1",
        chat_type="dm",
        thread_id="topic-1",
    )


def _event(proposal: dict) -> MessageEvent:
    return MessageEvent(
        text="private prompt",
        source=_source(),
        metadata={"_hermes_session_model_override": proposal},
    )


def _runner(*, config: GatewayConfig | None = None):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = config or GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True)}
    )
    runner._session_model_overrides = {}
    store = MagicMock()
    facade = SimpleNamespace(_store=store, set_model_override=AsyncMock())
    runner.session_store = store
    runner._async_session_store = facade
    return runner, facade


@pytest.mark.asyncio
async def test_fresh_session_pins_only_non_secret_override_fields() -> None:
    runner, facade = _runner()
    event = _event({
        "model": "qwen3.7-max",
        "provider": "opencode-go",
        "base_url": "https://example.invalid/v1",
        "api_key": "secret-must-be-dropped",
        "api_mode": "also-not-persisted",
    })
    entry = SimpleNamespace(session_key="session-1", model_override=None)

    applied = await runner._apply_proposed_session_model_override(
        event=event,
        source=_source(),
        session_entry=entry,
        is_new_session=True,
    )

    assert applied is True
    facade.set_model_override.assert_awaited_once_with(
        "session-1",
        {
            "model": "qwen3.7-max",
            "provider": "opencode-go",
        },
    )
    assert "_hermes_session_model_override" not in event.metadata


@pytest.mark.asyncio
async def test_ongoing_session_consumes_proposal_without_changing_model() -> None:
    runner, facade = _runner()
    event = _event({"model": "qwen3.7-max"})
    entry = SimpleNamespace(session_key="session-1", model_override=None)

    applied = await runner._apply_proposed_session_model_override(
        event=event,
        source=_source(),
        session_entry=entry,
        is_new_session=False,
    )

    assert applied is False
    facade.set_model_override.assert_not_awaited()
    assert "_hermes_session_model_override" not in event.metadata


@pytest.mark.asyncio
async def test_explicit_session_override_wins_over_plugin_proposal() -> None:
    runner, facade = _runner()
    event = _event({"model": "qwen3.7-max"})
    entry = SimpleNamespace(
        session_key="session-1",
        model_override={"model": "explicit-model"},
    )

    applied = await runner._apply_proposed_session_model_override(
        event=event,
        source=_source(),
        session_entry=entry,
        is_new_session=True,
    )

    assert applied is False
    facade.set_model_override.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_channel_override_wins_over_plugin_proposal() -> None:
    config = GatewayConfig(
        platforms={
            Platform.TELEGRAM: PlatformConfig(
                enabled=True,
                channel_overrides={
                    "topic-1": ChannelOverride(model="channel-model")
                },
            )
        }
    )
    runner, facade = _runner(config=config)
    event = _event({"model": "qwen3.7-max"})
    entry = SimpleNamespace(session_key="session-1", model_override=None)

    applied = await runner._apply_proposed_session_model_override(
        event=event,
        source=_source(),
        session_entry=entry,
        is_new_session=True,
    )

    assert applied is False
    facade.set_model_override.assert_not_awaited()
