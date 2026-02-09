"""Move cache_media_explicit and cooldown_minutes_explicit from config JSON into proper columns.

After this migration:
- feed.cache_media is NULL when using global default, or the per-feed override value
- feed.cooldown_minutes is NULL when using global default, or the per-feed override value
- config JSON no longer contains cache_media_explicit or cooldown_minutes_explicit
"""

import json

from sqlalchemy import text
from sqlmodel import Session


def migrate(engine):
    with Session(engine) as session:
        # Step 1: Recreate feed table with cache_media as nullable.
        # SQLite doesn't support ALTER COLUMN, so we use the rename-recreate pattern.
        session.exec(text("ALTER TABLE feed RENAME TO feed_old"))

        session.exec(
            text("""
            CREATE TABLE feed (
                id VARCHAR NOT NULL,
                type VARCHAR NOT NULL,
                name VARCHAR NOT NULL,
                config JSON,
                "limit" INTEGER NOT NULL,
                cache_media BOOLEAN,
                cooldown_minutes INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME,
                enabled INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (id)
            )
        """)
        )

        session.exec(
            text("""
            INSERT INTO feed (id, type, name, config, "limit", cache_media, cooldown_minutes, created_at, updated_at, enabled)
            SELECT id, type, name, config, "limit", cache_media, cooldown_minutes, created_at, updated_at, enabled
            FROM feed_old
        """)
        )

        session.exec(text("DROP TABLE feed_old"))
        session.commit()

        # Step 2: Migrate data — move _explicit values from config JSON into columns
        rows = session.exec(text("SELECT id, config FROM feed")).all()

        for feed_id, config_json in rows:
            config = (
                json.loads(config_json)
                if isinstance(config_json, str)
                else (config_json or {})
            )

            has_explicit_cache = "cache_media_explicit" in config
            has_explicit_cooldown = "cooldown_minutes_explicit" in config

            new_cache_media = config.pop("cache_media_explicit", None)
            new_cooldown_minutes = config.pop("cooldown_minutes_explicit", None)

            # Set column to explicit override or NULL
            session.exec(
                text(
                    "UPDATE feed SET cache_media = :cache, cooldown_minutes = :cooldown, config = :config WHERE id = :id"
                ).bindparams(
                    cache=new_cache_media if has_explicit_cache else None,
                    cooldown=new_cooldown_minutes if has_explicit_cooldown else None,
                    config=json.dumps(config),
                    id=feed_id,
                )
            )

        session.commit()
