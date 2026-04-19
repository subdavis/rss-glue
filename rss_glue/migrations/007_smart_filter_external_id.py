"""Replace post_id FK with post_external_id in filter_decision table.

This enables smart_filter composability - filters can now work with any
feed type (merges, other smart_filters, etc.) instead of requiring
direct Post table references.

Existing filter decisions are dropped. Smart filter feeds will need
to be reset and re-evaluated after this migration.
"""

from sqlalchemy import text
from sqlmodel import Session


def migrate(engine):
    """Recreate filter_decision table with post_external_id instead of post_id."""
    with Session(engine) as session:
        session.exec(text("DROP TABLE IF EXISTS filter_decision"))
        session.exec(
            text("""
            CREATE TABLE filter_decision (
                id INTEGER PRIMARY KEY,
                feed_id TEXT NOT NULL REFERENCES feed(id),
                post_external_id TEXT NOT NULL,
                approved BOOLEAN NOT NULL DEFAULT 0,
                reason TEXT,
                decided_at TIMESTAMP NOT NULL
            )
        """)
        )
        session.exec(
            text("CREATE INDEX ix_filter_decision_feed_id ON filter_decision(feed_id)")
        )
        session.exec(
            text(
                "CREATE INDEX ix_filter_decision_post_external_id ON filter_decision(post_external_id)"
            )
        )
        session.commit()
