"""Perplexity API client for live research search.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Wraps the Perplexity chat completions endpoint to perform research queries
and return structured ResearchItem stubs.
All methods respect dry_run mode — no HTTP calls are made when dry_run=True.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from src.personal_foundation.config import PerplexityConfig
    from src.personal_foundation.models import ResearchItem

log = logging.getLogger(__name__)

PERPLEXITY_API_BASE = "https://api.perplexity.ai"
PERPLEXITY_MODEL = "sonar"


class PerplexitySearchError(Exception):
    """Raised when the Perplexity API returns an error or the request fails."""


class PerplexityClient:
    """Wraps the Perplexity chat completions API for research queries.

    All methods check dry_run and return empty results when set, without
    making any outbound HTTP requests.
    """

    def __init__(self, config: "PerplexityConfig", dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run
        self._client = httpx.Client(
            base_url=PERPLEXITY_API_BASE,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    def search(
        self,
        query: str,
        max_age_hours: int = 24,
        scan_session_id: str | None = None,
    ) -> list["ResearchItem"]:
        """Search Perplexity for research items matching the query.

        Sends the query to the Perplexity chat completions endpoint using the
        ``sonar`` model with a recency filter. Parses citations from the
        response to build ``ResearchItem`` stubs.

        Args:
            query: The search query string.
            max_age_hours: Maximum age of results in hours. Currently maps to
                Perplexity's ``search_recency_filter`` (24h → "day").
            scan_session_id: Optional session ID to group items from one scan
                run. A new UUID is generated if not provided.

        Returns:
            List of ``ResearchItem`` stubs with ``item_id``, ``source_url``,
            ``title``, ``published_at``, empty ``pillar_scores``,
            ``relevance_score=0``, ``scan_session_id``, and ``summary=None``.
            Returns an empty list when ``dry_run=True``.

        Raises:
            PerplexitySearchError: If the HTTP request fails or the API
                returns a non-2xx status code.
        """
        from src.personal_foundation.models import ResearchItem

        if self.dry_run:
            log.info(
                "[dry_run] perplexity_client.search query=%r max_age_hours=%d",
                query,
                max_age_hours,
            )
            return []

        session_id = scan_session_id or str(uuid.uuid4())
        recency_filter = _hours_to_recency_filter(max_age_hours)

        payload = {
            "model": PERPLEXITY_MODEL,
            "messages": [{"role": "user", "content": query}],
            "search_recency_filter": recency_filter,
        }

        try:
            resp = self._client.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise PerplexitySearchError(
                f"Perplexity request failed: {exc}"
            ) from exc

        if resp.status_code >= 400:
            raise PerplexitySearchError(
                f"Perplexity API error {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.json()
        citations: list[str] = data.get("citations", [])

        items: list[ResearchItem] = []
        for url in citations:
            item = ResearchItem(
                item_id=str(uuid.uuid4()),
                source_url=url,
                title=_title_from_url(url),
                published_at=datetime.now(timezone.utc),
                pillar_scores={},
                relevance_score=0,
                scan_session_id=session_id,
                summary=None,
            )
            items.append(item)

        log.info(
            "perplexity_client.search query=%r returned %d citations",
            query,
            len(items),
        )
        return items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hours_to_recency_filter(max_age_hours: int) -> str:
    """Map a max-age in hours to a Perplexity search_recency_filter value.

    Perplexity supports: "hour", "day", "week", "month".
    """
    if max_age_hours <= 1:
        return "hour"
    if max_age_hours <= 24:
        return "day"
    if max_age_hours <= 168:  # 7 days
        return "week"
    return "month"


def _title_from_url(url: str) -> str:
    """Derive a best-effort title from a URL when no title metadata is available."""
    try:
        # Strip scheme and use the path as a readable title placeholder
        without_scheme = url.split("://", 1)[-1]
        # Remove trailing slashes and query strings
        path = without_scheme.split("?")[0].rstrip("/")
        return path or url
    except Exception:
        return url
