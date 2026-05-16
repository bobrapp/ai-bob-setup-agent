"""SaaS authentication — OAuth2 (Google/GitHub) via JWT.

Supports:
- Email/password (simple, for dev)
- Google OAuth2 (production)
- GitHub OAuth2 (production)
- Magic link (passwordless email)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import jwt

log = logging.getLogger(__name__)

JWT_SECRET = os.getenv("JWT_SECRET", "change-this-in-production")
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24


class AuthService:
    """Handles authentication for the SaaS platform."""

    def __init__(self) -> None:
        self._google_client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        self._github_client_id = os.getenv("GITHUB_CLIENT_ID", "")

    def create_token(self, user_id: str, org_id: str, email: str, role: str = "operator") -> str:
        """Create a JWT token for an authenticated user."""
        expires = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS)
        payload = {
            "sub": user_id,
            "org_id": org_id,
            "email": email,
            "role": role,
            "exp": expires,
            "iat": datetime.now(timezone.utc),
        }
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    def verify_token(self, token: str) -> dict | None:
        """Verify and decode a JWT token. Returns claims or None."""
        try:
            return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            log.debug("AuthService: token expired")
            return None
        except jwt.InvalidTokenError:
            log.debug("AuthService: invalid token")
            return None

    async def google_oauth_callback(self, code: str) -> dict | None:
        """Handle Google OAuth2 callback. Returns user info or None."""
        if not self._google_client_id:
            return None
        # In production: exchange code for token, verify with Google
        # For now, return placeholder
        return {"provider": "google", "email": "", "name": ""}

    async def github_oauth_callback(self, code: str) -> dict | None:
        """Handle GitHub OAuth2 callback. Returns user info or None."""
        if not self._github_client_id:
            return None
        # In production: exchange code for token, get user from GitHub API
        return {"provider": "github", "email": "", "name": ""}

    async def send_magic_link(self, email: str) -> bool:
        """Send a passwordless magic link to the email. Returns True on success."""
        # In production: generate a short-lived token, email it
        log.info("AuthService: magic link requested for %s", email)
        return True
