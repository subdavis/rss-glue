"""Shared test fixtures."""

import respx
from sqlmodel import Session, SQLModel, create_engine

import pytest


@pytest.fixture
def db_session():
    """In-memory SQLite session for testing."""
    engine = create_engine("sqlite://", echo=False)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def mock_api():
    """Activate respx to intercept all httpx requests.

    Usage in tests:
        def test_something(mock_api):
            mock_api.get("https://api.example.com/data").respond(json={...})
            # code that uses httpx will be intercepted
    """
    with respx.mock(assert_all_called=False) as respx_mock:
        yield respx_mock
