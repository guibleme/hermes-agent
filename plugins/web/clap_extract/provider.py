"""clap-extract provider — lightweight URL-to-markdown extraction.

Subclasses :class:`agent.web_search_provider.WebSearchProvider` and
implements ``extract()`` via a local clap-extract server.

Config keys this provider responds to::

    web:
      extract_backend: "clap-extract"

No auth/API key needed — it talks to ``http://localhost:3003``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)

_CLAP_EXTRACT_URL = "http://localhost:3003"


class ClapExtractProvider(WebSearchProvider):
    """Extract-only provider using the local clap-extract server."""

    @property
    def name(self) -> str:
        return "clap-extract"

    @property
    def display_name(self) -> str:
        return "clap-extract (local)"

    def is_available(self) -> bool:
        """Cheap availability check — port 3003 reachable."""
        import socket
        try:
            s = socket.create_connection(("127.0.0.1", 3003), timeout=1)
            s.close()
            return True
        except (OSError, TimeoutError):
            return False

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        return {"success": False, "error": "clap-extract is extract-only, use a search backend"}

    def _do_extract_one(self, url: str) -> Dict[str, Any]:
        """Extract readable markdown from a single URL via the local server."""
        import json
        import urllib.request
        import urllib.error
        import urllib.parse

        try:
            req = urllib.request.Request(
                f"{_CLAP_EXTRACT_URL}/extract?url={urllib.parse.quote(url, safe='')}",
                method="GET",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            logger.warning("clap-extract HTTP error on %s: %s", url, exc)
            return {"url": url, "title": "", "content": "", "error": f"HTTP {exc.code}"}
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.warning("clap-extract connection error on %s: %s", url, exc)
            return {"url": url, "title": "", "content": "", "error": str(exc)}
        except Exception as exc:
            logger.warning("clap-extract error on %s: %s", url, exc)
            return {"url": url, "title": "", "content": "", "error": str(exc)}

        if not data.get("success"):
            return {
                "url": url,
                "title": "",
                "content": "",
                "error": data.get("error", "Unknown error"),
            }

        return {
            "url": url,
            "title": data.get("title", ""),
            "content": data.get("content", ""),
            "raw_content": data.get("content", ""),
        }

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        """Extract readable markdown from one or more URLs via the local server.

        Matches the standard WebSearchProvider.extract() signature so the
        web_extract_tool dispatcher can call it directly.
        """
        from tools.interrupt import is_interrupted

        if is_interrupted():
            return [{"url": u, "error": "Interrupted", "title": ""} for u in urls]

        results: List[Dict[str, Any]] = []
        for url in urls:
            results.append(self._do_extract_one(url))

        return results
