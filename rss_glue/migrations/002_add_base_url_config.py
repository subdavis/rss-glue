"""Add base_url to system configuration.

This migration adds a default base_url configuration value.
"""

from sqlalchemy import text
from sqlmodel import Session


def migrate(engine):
    """Add base_url system config with default value."""
    with Session(engine) as session:
        # Insert default base_url config if it doesn't exist
        session.exec(text("""
            INSERT INTO system_config (key, value)
            SELECT 'base_url', 'http://localhost:8000'
            WHERE NOT EXISTS (
                SELECT 1 FROM system_config WHERE key = 'base_url'
            )
        """))
        session.commit()