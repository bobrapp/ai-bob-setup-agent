"""Granola meeting notes API client.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Wraps the Granola export API for retrieving meeting notes, transcripts, and
action items. All methods respect dry_run mode — no HTTP calls are made when
dry_run=True.

Note: The Granola API base URL (https://api.granola.so/v1) is a placeholder.
Verify the actual endpoint against Granola's current API documentation before
deploying to production.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    pass

from src.personal_foundation.models import MeetingNotes

log = logging.getLogger(__name__)

GRANOLA_API_BASE = "https://api.granola.so/v1"


class GranolaAPIError(Exception):
    """Raised when the Granola API returns an error response."""


class GranolaClient:
    """Wraps the Granola export API for meeting notes retrieval.

    All methods check dry_run and return stub data instead of calling the
    API when set.

    Args:
        granola_api_key: Granola API key for authentication.
        dry_run: When True, all methods return stub data without making
                 any outbound HTTP requests.
    """

    def __init__(self, granola_api_key: str, dry_run: bool = False) -> None:
        self.granola_api_key = granola_api_key
        self.dry_run = dry_run
        self._client = httpx.Client(
            base_url=GRANOLA_API_BASE,
            headers={
                "Authorization": f"Bearer {granola_api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_meeting_notes(self, meeting_id: str) -> MeetingNotes:
        """Fetch meeting notes for a specific meeting by ID.

        Returns a MeetingNotes dataclass with title, date, attendees,
        summary, action_items, and transcript.

        Args:
            meeting_id: The Granola meeting identifier.

        Returns:
            MeetingNotes populated from the API response, or stub data
            when dry_run=True or on API failure.
        """
        if self.dry_run:
            log.info("[dry_run] granola_client.get_meeting_notes meeting_id=%s", meeting_id)
            return self._stub_meeting_notes(meeting_id)

        try:
            resp = self._client.get(f"/meetings/{meeting_id}/notes")
            self._raise_for_status(resp)
            data = resp.json()
            return self._parse_meeting_notes(meeting_id, data)
        except GranolaAPIError as exc:
            log.error("granola_client.get_meeting_notes API error: %s", exc)
            return self._stub_meeting_notes(meeting_id)
        except httpx.HTTPError as exc:
            log.error("granola_client.get_meeting_notes HTTP error: %s", exc)
            return self._stub_meeting_notes(meeting_id)

    def list_recent_meetings(self, days: int = 7) -> list[dict]:
        """Return a list of recent meeting stubs for the last N days.

        Each stub contains: id, title, date, attendees.

        Args:
            days: Number of days to look back. Defaults to 7.

        Returns:
            List of meeting stub dicts, or an empty list on dry_run or
            API failure.
        """
        if self.dry_run:
            log.info("[dry_run] granola_client.list_recent_meetings days=%d", days)
            return [
                {
                    "id": "dry-run-meeting-001",
                    "title": "[dry-run] Weekly Sync",
                    "date": datetime.now(timezone.utc).isoformat(),
                    "attendees": ["bob@example.com", "ken@example.com"],
                }
            ]

        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        try:
            resp = self._client.get(
                "/meetings",
                params={"since": since, "limit": 100},
            )
            self._raise_for_status(resp)
            meetings = []
            for m in resp.json().get("meetings", []):
                meetings.append(
                    {
                        "id": str(m.get("id", "")),
                        "title": m.get("title", ""),
                        "date": m.get("date", ""),
                        "attendees": m.get("attendees", []),
                    }
                )
            return meetings
        except GranolaAPIError as exc:
            log.error("granola_client.list_recent_meetings API error: %s", exc)
            return []
        except httpx.HTTPError as exc:
            log.error("granola_client.list_recent_meetings HTTP error: %s", exc)
            return []

    def find_meetings_with_attendees(
        self,
        attendee_emails: list[str],
        limit: int = 5,
    ) -> list[MeetingNotes]:
        """Find the most recent meetings that include at least one of the given attendees.

        Args:
            attendee_emails: List of email addresses to search for.
            limit: Maximum number of meetings to return. Defaults to 5.

        Returns:
            List of MeetingNotes for matching meetings, sorted by date
            descending. Returns stub data when dry_run=True, or an empty
            list on API failure.
        """
        if self.dry_run:
            log.info(
                "[dry_run] granola_client.find_meetings_with_attendees "
                "attendees=%s limit=%d",
                attendee_emails,
                limit,
            )
            return [
                self._stub_meeting_notes(
                    f"dry-run-meeting-{i:03d}",
                    attendees=attendee_emails[:2],
                )
                for i in range(min(limit, 2))
            ]

        try:
            resp = self._client.get(
                "/meetings/search",
                params={
                    "attendees": ",".join(attendee_emails),
                    "limit": limit,
                    "sort": "date_desc",
                },
            )
            self._raise_for_status(resp)
            results = []
            for m in resp.json().get("meetings", []):
                meeting_id = str(m.get("id", ""))
                notes = self._parse_meeting_notes(meeting_id, m)
                results.append(notes)
            return results[:limit]
        except GranolaAPIError as exc:
            log.error("granola_client.find_meetings_with_attendees API error: %s", exc)
            return []
        except httpx.HTTPError as exc:
            log.error("granola_client.find_meetings_with_attendees HTTP error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_meeting_notes(self, meeting_id: str, data: dict) -> MeetingNotes:
        """Parse a Granola API response dict into a MeetingNotes dataclass."""
        raw_date = data.get("date") or data.get("start_time") or data.get("created_at")
        if raw_date:
            try:
                date = datetime.fromisoformat(raw_date)
            except (ValueError, TypeError):
                date = datetime.now(timezone.utc)
        else:
            date = datetime.now(timezone.utc)

        # Attendees may be a list of strings or a list of dicts with an email key
        raw_attendees = data.get("attendees", [])
        attendees: list[str] = []
        for a in raw_attendees:
            if isinstance(a, str):
                attendees.append(a)
            elif isinstance(a, dict):
                attendees.append(a.get("email") or a.get("name") or str(a))

        # Action items may be a list of strings or dicts
        raw_actions = data.get("action_items", [])
        action_items: list[dict[str, str]] = []
        for item in raw_actions:
            if isinstance(item, str):
                action_items.append({"description": item, "assignee": "", "due_date": ""})
            elif isinstance(item, dict):
                action_items.append(
                    {
                        "description": item.get("description", ""),
                        "assignee": item.get("assignee", ""),
                        "due_date": item.get("due_date", ""),
                    }
                )

        return MeetingNotes(
            meeting_id=meeting_id,
            title=data.get("title", ""),
            date=date,
            attendees=attendees,
            summary=data.get("summary", ""),
            action_items=action_items,
            transcript=data.get("transcript") or data.get("transcript_text"),
        )

    def _stub_meeting_notes(
        self,
        meeting_id: str,
        attendees: list[str] | None = None,
    ) -> MeetingNotes:
        """Return a stub MeetingNotes for dry_run or error fallback."""
        return MeetingNotes(
            meeting_id=meeting_id,
            title="[stub] Meeting Notes",
            date=datetime.now(timezone.utc),
            attendees=attendees or ["bob@example.com"],
            summary="[stub] No summary available.",
            action_items=[],
            transcript=None,
        )

    def _raise_for_status(self, resp: httpx.Response) -> None:
        """Raise GranolaAPIError for 4xx/5xx responses."""
        if resp.status_code >= 400:
            raise GranolaAPIError(
                f"Granola API error {resp.status_code}: {resp.text[:200]}"
            )

    def __enter__(self) -> "GranolaClient":
        return self

    def __exit__(self, *args) -> None:
        self._client.close()
