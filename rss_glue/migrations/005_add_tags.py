"""Add tag and feed_tag tables."""

from sqlalchemy import text
from sqlmodel import Session


def migrate(engine):
    with Session(engine) as session:
        # Create tag table
        session.exec(
            text("""
            CREATE TABLE IF NOT EXISTS tag (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR NOT NULL UNIQUE
            )
        """)
        )
        session.exec(text("CREATE INDEX IF NOT EXISTS ix_tag_name ON tag (name)"))

        # Create feed_tag table
        session.exec(
            text("""
            CREATE TABLE IF NOT EXISTS feed_tag (
                feed_id VARCHAR NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (feed_id, tag_id),
                FOREIGN KEY(feed_id) REFERENCES feed (id),
                FOREIGN KEY(tag_id) REFERENCES tag (id)
            )
        """)
        )
        session.commit()
