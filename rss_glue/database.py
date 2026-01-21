"""Database setup and session management."""

from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, create_engine

from rss_glue.migrations import run_migrations

DATABASE_URL = "sqlite:///rss_glue.db"

engine = create_engine(DATABASE_URL, echo=False)


def create_db_and_tables():
    """Create all database tables."""
    # Check if this is a fresh database before creating tables
    inspector = inspect(engine)
    fresh_db = not inspector.get_table_names()

    SQLModel.metadata.create_all(engine)
    run_migrations(engine, fresh_db=fresh_db)


def get_session():
    """Dependency for FastAPI to get a database session."""
    with Session(engine) as session:
        yield session
