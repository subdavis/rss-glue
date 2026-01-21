"""Authentication routes."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from rss_glue.database import get_session
from rss_glue.models.user import User
from rss_glue.services.auth import (
    clear_auth_cookie,
    get_current_user_optional,
    has_any_users,
    set_auth_cookie,
)
from rss_glue.templates import templates

router = APIRouter()


@router.get("/login")
def login_page(
    request: Request,
    next: str = "/",
    session: Session = Depends(get_session),
):
    """Show login page, or redirect to setup if no users exist."""
    # If no users exist, redirect to setup
    if not has_any_users(session):
        return RedirectResponse(url="/auth/setup", status_code=303)

    # If already logged in, redirect to next
    user = get_current_user_optional(request, session)
    if user is not None:
        return RedirectResponse(url=next, status_code=303)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "next": next, "error": None},
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    session: Session = Depends(get_session),
):
    """Process login form submission."""
    # Find user by username
    user = session.exec(select(User).where(User.username == username)).first()

    if user is None or user.id is None or not user.verify_password(password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "next": next, "error": "Invalid username or password"},
            status_code=401,
        )

    # Create session and redirect
    response = RedirectResponse(url=next, status_code=303)
    return set_auth_cookie(response, user.id)


@router.get("/setup")
def setup_page(
    request: Request,
    session: Session = Depends(get_session),
):
    """Show first-user setup page, or redirect to login if users exist."""
    # If users already exist, redirect to login
    if has_any_users(session):
        return RedirectResponse(url="/auth/login", status_code=303)

    return templates.TemplateResponse(
        "setup.html",
        {"request": request, "error": None},
    )


@router.post("/setup")
def setup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    session: Session = Depends(get_session),
):
    """Process first-user setup form submission."""
    # If users already exist, redirect to login
    if has_any_users(session):
        return RedirectResponse(url="/auth/login", status_code=303)

    # Validate inputs
    error = None
    if len(username) < 3:
        error = "Username must be at least 3 characters"
    elif len(password) < 8:
        error = "Password must be at least 8 characters"
    elif password != password_confirm:
        error = "Passwords do not match"

    if error:
        return templates.TemplateResponse(
            "setup.html",
            {"request": request, "error": error},
            status_code=400,
        )

    # Create the user
    user = User(
        username=username,
        password_hash=User.hash_password(password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    # Log them in and redirect to home
    response = RedirectResponse(url="/", status_code=303)
    assert user.id is not None
    return set_auth_cookie(response, user.id)


@router.get("/logout")
def logout(request: Request):
    """Log out and redirect to home."""
    response = RedirectResponse(url="/", status_code=303)
    return clear_auth_cookie(response)
