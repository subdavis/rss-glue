"""Authentication utilities and dependencies."""

import os
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer
from sqlmodel import Session, select

from rss_glue.database import get_session
from rss_glue.models.user import User

# Secret key for signing cookies - use env var in production
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
COOKIE_NAME = "session"

# Create serializer for signing cookies
serializer = URLSafeSerializer(SECRET_KEY)


def create_session_cookie(user_id: int) -> str:
    """Create a signed session cookie value."""
    return serializer.dumps({"user_id": user_id})


def parse_session_cookie(cookie_value: str) -> Optional[int]:
    """Parse and verify a session cookie, returning user_id or None."""
    try:
        data = serializer.loads(cookie_value)
        return data.get("user_id")
    except BadSignature:
        return None


def get_user_count(session: Session) -> int:
    """Get the total number of users in the database."""
    return session.exec(select(User)).all().__len__()


def has_any_users(session: Session) -> bool:
    """Check if any users exist in the database."""
    result = session.exec(select(User).limit(1)).first()
    return result is not None


def get_current_user_optional(
    request: Request,
    session: Session = Depends(get_session),
) -> Optional[User]:
    """Get the current user from session cookie, or None if not authenticated.

    Use this dependency when you want to check auth status but not require it.
    """
    cookie_value = request.cookies.get(COOKIE_NAME)
    if not cookie_value:
        return None

    user_id = parse_session_cookie(cookie_value)
    if user_id is None:
        return None

    return session.get(User, user_id)


def require_auth(
    request: Request,
    session: Session = Depends(get_session),
) -> User:
    """Require authentication, redirecting to login if not authenticated.

    Use this dependency on routes that require authentication.
    Redirects to /auth/setup if no users exist, otherwise to /auth/login.
    """
    user = get_current_user_optional(request, session)
    if user is not None:
        return user

    # Not authenticated - check if we need setup or login
    if not has_any_users(session):
        raise HTTPException(
            status_code=307,
            headers={"Location": "/auth/setup"},
        )
    else:
        # Include the original URL as a redirect parameter
        next_url = str(request.url.path)
        raise HTTPException(
            status_code=307,
            headers={"Location": f"/auth/login?next={next_url}"},
        )


def set_auth_cookie(response: RedirectResponse, user_id: int) -> RedirectResponse:
    """Set the authentication cookie on a response."""
    cookie_value = create_session_cookie(user_id)
    response.set_cookie(
        key=COOKIE_NAME,
        value=cookie_value,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,  # 30 days
    )
    return response


def clear_auth_cookie(response: RedirectResponse) -> RedirectResponse:
    """Clear the authentication cookie from a response."""
    response.delete_cookie(key=COOKIE_NAME)
    return response
