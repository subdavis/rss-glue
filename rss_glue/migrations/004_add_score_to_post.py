"""Add score column to post table.

This migration adds an optional 'score' column to the post table for feeds
that provide post scores (e.g., Reddit upvotes).
"""

from sqlalchemy import text
from sqlmodel import Session


def migrate(engine):
    """Add score column to post table."""
    with Session(engine) as session:
        session.exec(
            text("""
            ALTER TABLE post ADD COLUMN score INTEGER
        """)
        )
        session.commit()
