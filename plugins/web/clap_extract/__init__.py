"""clap-extract plugin — bundled, auto-loaded."""

from __future__ import annotations

from plugins.web.clap_extract.provider import ClapExtractProvider


def register(ctx) -> None:
    """Register the clap-extract provider with the plugin context."""
    ctx.register_web_search_provider(ClapExtractProvider())
