"""Add enabled column to feed table.

This migration adds an 'enabled' column to the feed table with a default value of TRUE.
"""

from sqlalchemy import text
from sqlmodel import Session


def migrate(engine):
    """Add enabled column to feed table."""
    with Session(engine) as session:
        # Add enabled column with default value of TRUE (1 in SQLite)
        session.exec(
            text("""
            ALTER TABLE feed ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1
        """)
        )
        session.commit()
