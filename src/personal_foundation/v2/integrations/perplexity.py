"""Perplexity API integration — live web search for the Research Agent."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx

from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"


class PerplexitySearch:
    """Searches Perplexity for AI governance publications."""

    def __init__(self, store: StateStore, dry_run: bool = False) -> None:
        self.store = store
        self.dry_run = dry_run
        self._api_key = os.getenv("PERPLEXITY_API_KEY", "")
        self._client = httpx.AsyncClient(timeout=30)

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str = "AI governance responsible AI regulation news today") -> list[dict]:
        """Search Perplexity and return structured results."""
        if not self.is_configured:
            log.warning("PerplexitySearch: PERPLEXITY_API_KEY not set")
            return []

        if self.dry_run:
            log.info("[dry_run] PerplexitySearch: would search '%s'", query)
            return [{"title": "[dry-run] Sample result", "url": "https://example.com", "snippet": "Dry run result"}]

        try:
            resp = await self._client.post(
                PERPLEXITY_API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.1-sonar-small-128k-online",
                    "messages": [
                        {"role": "system", "content": "Search for recent AI governance publications and news. Return structured results with titles and URLs."},
                        {"role": "user", "content": query},
                    ],
                    "max_tokens": 1024,
                    "return_citations": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # Extract citations/results
            results = []
            citations = data.get("citations", [])
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            for i, url in enumerate(citations[:10]):
                results.append({
                    "title": f"Result {i+1}",
                    "url": url,
                    "snippet": content[:200] if i == 0 else "",
                    "found_at": datetime.now(timezone.utc).isoformat(),
                })

            self.store.log_audit(
                agent="personal/research_scanner", action="perplexity_search",
                status="success", model="llama-3.1-sonar-small-128k-online",
                result_summary=f"Found {len(results)} results for: {query[:50]}",
            )
            return results

        except Exception as exc:
            log.error("PerplexitySearch: failed: %s", exc)
            self.store.log_audit(
                agent="personal/research_scanner", action="perplexity_search",
                status="failure", result_summary=f"Search failed: {type(exc).__name__}",
            )
            return []
