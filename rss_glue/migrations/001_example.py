"""Example migration - this is a no-op placeholder.

Delete this file and create real migrations as needed.
Each migration file must have a `migrate(engine)` function.

Example real migration:

    from sqlalchemy import text
    from sqlmodel import Session

    def migrate(engine):
        with Session(engine) as session:
            session.exec(text("ALTER TABLE post ADD COLUMN score INTEGER DEFAULT 0"))
            session.commit()
"""


def migrate(engine):
    """Placeholder migration - does nothing."""
    pass
