"""Simple database migrations module.

Migrations are Python files in this directory named like:
    001_initial_setup.py
    002_add_score_column.py

Each migration file must have a `migrate(engine)` function that receives the SQLAlchemy engine.
Migrations are run once in order and tracked in the `schema_version` table.
"""

import importlib
from pathlib import Path
from typing import Callable

from sqlalchemy import text
from sqlmodel import Session


def get_applied_migrations(engine) -> set[str]:
    """Get set of already-applied migration names."""
    with Session(engine) as session:
        # Create schema_version table if it doesn't exist
        session.exec(
            text("""
            CREATE TABLE IF NOT EXISTS schema_version (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        )
        session.commit()

        result = session.exec(text("SELECT name FROM schema_version"))
        return {row[0] for row in result}


def mark_migration_applied(engine, name: str):
    """Mark a migration as applied."""
    with Session(engine) as session:
        session.execute(
            text("INSERT INTO schema_version (name) VALUES (:name)"), {"name": name}
        )
        session.commit()


def discover_migrations() -> list[tuple[str, Callable]]:
    """Discover all migration modules and return them sorted by name."""
    migrations_dir = Path(__file__).parent
    migrations = []

    for file in sorted(migrations_dir.glob("[0-9]*.py")):
        module_name = file.stem
        module = importlib.import_module(f"rss_glue.migrations.{module_name}")
        if hasattr(module, "migrate"):
            migrations.append((module_name, module.migrate))

    return migrations


def is_fresh_database(engine) -> bool:
    """Check if this is a fresh database (no migrations have ever been applied)."""
    with Session(engine) as session:
        result = session.exec(text("SELECT COUNT(*) FROM schema_version"))
        return result.one()[0] == 0


def run_migrations(engine, fresh_db: bool = False):
    """Run all pending migrations in order.

    Args:
        engine: SQLAlchemy engine
        fresh_db: If True, mark all migrations as applied without running them
                  (used when create_all() already created the current schema)
    """
    applied = get_applied_migrations(engine)
    migrations = discover_migrations()

    if fresh_db and not applied:
        # Fresh database - schema is already current from create_all()
        # Mark all migrations as applied without running them
        print("Fresh database detected, marking all migrations as applied")
        for name, _ in migrations:
            mark_migration_applied(engine, name)
            print(f"  ✓ {name} marked as applied")
        return

    for name, migrate_fn in migrations:
        if name not in applied:
            print(f"Applying migration: {name}")
            migrate_fn(engine)
            mark_migration_applied(engine, name)
            print(f"  ✓ {name} applied")

    if not any(name not in applied for name, _ in migrations):
        print("No pending migrations")
