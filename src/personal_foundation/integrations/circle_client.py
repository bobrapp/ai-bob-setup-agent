"""Circle.so Admin API client.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Wraps the Circle Admin API for community management actions.
All methods respect dry_run mode — no HTTP calls are made when dry_run=True.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from src.personal_foundation.config import CircleConfig
    from src.personal_foundation.models import CircleMember, CirclePost

log = logging.getLogger(__name__)

CIRCLE_API_BASE = "https://app.circle.so/api/v1"
CIRCLE_API_V2_BASE = "https://app.circle.so/api/v2"


class CircleAPIError(Exception):
    """Raised when the Circle Admin API returns an error."""


class CircleClient:
    """Wraps Circle Admin API. Uses Headless Auth JWT for DM delivery.

    All methods check dry_run and log instead of calling the API when set.
    """

    def __init__(self, config: "CircleConfig", dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run
        self._client = httpx.Client(
            base_url=CIRCLE_API_BASE,
            headers={
                "Authorization": f"Token {config.api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    # ------------------------------------------------------------------
    # Member operations
    # ------------------------------------------------------------------

    def get_member(self, member_id: str) -> "CircleMember":
        """Fetch a community member by ID."""
        from src.personal_foundation.models import CircleMember

        if self.dry_run:
            log.info("[dry_run] circle_client.get_member member_id=%s", member_id)
            return CircleMember(member_id=member_id, display_name="[dry-run member]")

        resp = self._client.get(
            f"/community_members/{member_id}",
            params={"community_id": self.config.community_id},
        )
        self._raise_for_status(resp)
        data = resp.json()
        return CircleMember(
            member_id=str(data.get("id", member_id)),
            display_name=data.get("name", ""),
            bio=data.get("bio", ""),
            role=data.get("headline", ""),
        )

    def send_dm(self, member_id: str, body: str) -> bool:
        """Send a direct message to a member via Headless Auth JWT.

        Returns True on success, False on failure.
        """
        if self.dry_run:
            log.info(
                "[dry_run] circle_client.send_dm member_id=%s body_len=%d",
                member_id,
                len(body),
            )
            return True

        try:
            resp = httpx.post(
                f"{CIRCLE_API_V2_BASE}/direct_messages",
                headers={
                    "Authorization": f"Bearer {self.config.headless_auth_jwt}",
                    "Content-Type": "application/json",
                },
                json={
                    "community_id": self.config.community_id,
                    "recipient_id": member_id,
                    "body": body,
                },
                timeout=30.0,
            )
            return resp.status_code in (200, 201)
        except httpx.HTTPError as exc:
            log.error("circle_client.send_dm failed: %s", exc)
            return False

    def post_to_space(self, space_id: str, body: str, title: str = "") -> dict:
        """Create a post in a Circle.so space.

        Returns the created post data dict, or empty dict on dry_run.
        """
        if self.dry_run:
            log.info(
                "[dry_run] circle_client.post_to_space space_id=%s title=%r",
                space_id,
                title,
            )
            return {"id": "dry_run_post_id", "space_id": space_id}

        resp = self._client.post(
            "/posts",
            json={
                "community_id": self.config.community_id,
                "space_id": space_id,
                "name": title or body[:80],
                "body": body,
                "status": "published",
            },
        )
        self._raise_for_status(resp)
        return resp.json()

    def apply_tag(self, member_id: str, tag: str) -> bool:
        """Apply an interest tag to a member's profile.

        Returns True on success.
        """
        if self.dry_run:
            log.info(
                "[dry_run] circle_client.apply_tag member_id=%s tag=%r",
                member_id,
                tag,
            )
            return True

        try:
            resp = self._client.post(
                f"/community_members/{member_id}/add_tag",
                json={"community_id": self.config.community_id, "tag": tag},
            )
            return resp.status_code in (200, 201)
        except httpx.HTTPError as exc:
            log.error("circle_client.apply_tag failed: %s", exc)
            return False

    def flag_post(self, post_id: str, reason: str) -> bool:
        """Flag a post for human review.

        Returns True on success. Does NOT delete or hide the post.
        """
        if self.dry_run:
            log.info(
                "[dry_run] circle_client.flag_post post_id=%s reason=%r",
                post_id,
                reason,
            )
            return True

        try:
            resp = self._client.post(
                f"/posts/{post_id}/flag",
                json={"community_id": self.config.community_id, "reason": reason},
            )
            return resp.status_code in (200, 201)
        except httpx.HTTPError as exc:
            log.error("circle_client.flag_post failed: %s", exc)
            return False

    def list_recent_posts(
        self, days: int = 7, space_id: str | None = None
    ) -> list["CirclePost"]:
        """List posts published within the last N days.

        Args:
            days: Number of days to look back.
            space_id: Optional space filter. If None, searches all spaces.

        Returns:
            List of CirclePost objects sorted by published_at descending.
        """
        from src.personal_foundation.models import CirclePost

        if self.dry_run:
            log.info(
                "[dry_run] circle_client.list_recent_posts days=%d space_id=%s",
                days,
                space_id,
            )
            return []

        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        params: dict = {
            "community_id": self.config.community_id,
            "per_page": 100,
            "sort": "latest",
            "published_after": since,
        }
        if space_id:
            params["space_id"] = space_id

        try:
            resp = self._client.get("/posts", params=params)
            self._raise_for_status(resp)
            posts = []
            for p in resp.json().get("records", []):
                posts.append(
                    CirclePost(
                        post_id=str(p.get("id", "")),
                        space_id=str(p.get("space_id", "")),
                        author_member_id=str(p.get("user_id", "")),
                        title=p.get("name", ""),
                        body=p.get("body", ""),
                        published_at=datetime.fromisoformat(
                            p.get("published_at", datetime.now(timezone.utc).isoformat())
                        ),
                        reactions=p.get("likes_count", 0),
                        comments=p.get("comments_count", 0),
                        tags=[t.get("name", "") for t in p.get("tags", [])],
                    )
                )
            return posts
        except httpx.HTTPError as exc:
            log.error("circle_client.list_recent_posts failed: %s", exc)
            return []

    def get_post_engagement(self, post_id: str) -> int:
        """Return the engagement score (reactions + comments) for a post."""
        if self.dry_run:
            log.info(
                "[dry_run] circle_client.get_post_engagement post_id=%s", post_id
            )
            return 0

        try:
            resp = self._client.get(
                f"/posts/{post_id}",
                params={"community_id": self.config.community_id},
            )
            self._raise_for_status(resp)
            data = resp.json()
            return data.get("likes_count", 0) + data.get("comments_count", 0)
        except httpx.HTTPError as exc:
            log.error("circle_client.get_post_engagement failed: %s", exc)
            return 0

    # ------------------------------------------------------------------
    # Retry helper (used by Welcomer — Requirement 6.4)
    # ------------------------------------------------------------------

    def with_exponential_backoff(
        self,
        fn,
        *args,
        initial_delay: float = 30.0,
        max_window_seconds: float = 1800.0,
        **kwargs,
    ):
        """Call fn(*args, **kwargs) with exponential backoff on failure.

        Starts at initial_delay seconds, doubles each attempt.
        Stops after max_window_seconds total elapsed time.

        Returns the result of fn on success, or raises the last exception
        after the window is exhausted.
        """
        delay = initial_delay
        elapsed = 0.0
        last_exc: Exception | None = None

        while elapsed < max_window_seconds:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "circle_client.backoff retry in %.0fs (elapsed=%.0fs)",
                    delay,
                    elapsed,
                )
                time.sleep(delay)
                elapsed += delay
                delay = min(delay * 2, max_window_seconds - elapsed)

        raise last_exc or RuntimeError("Backoff window exhausted")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            raise CircleAPIError(
                f"Circle API error {resp.status_code}: {resp.text[:200]}"
            )
