"""JSON config to database synchronization."""

from rss_glue.handlers.smart_filter import SmartFilterFeedHandler
from rss_glue.handlers.digest import DigestFeedHandler

from sqlalchemy import text
from sqlmodel import Session, col, select

from rss_glue.feeds import FeedRegistry
from rss_glue.models.db import Feed, FeedRelationship, FeedTag, SystemConfig, Tag
from rss_glue.models.feed_config import FeedConfigBase


def resolve_feed_cache_media(feed: Feed, session: Session) -> bool:
    """Resolve effective cache_media: per-feed override or global default."""
    if feed.cache_media is not None:
        return feed.cache_media
    return get_global_cache_media(session)


def get_system_config_value(session: Session, key: str) -> str | None:
    """Helper to get a system config value by key."""
    system_config = session.get(SystemConfig, key)
    return system_config.value if system_config else None


def resolve_feed_cooldown(feed: Feed, session: Session) -> int:
    """Resolve effective cooldown_minutes: per-feed override or global default."""
    if feed.cooldown_minutes is not None:
        return feed.cooldown_minutes
    return get_global_cooldown(session)


def get_global_cooldown(session: Session) -> int:
    """Return the global default cooldown_minutes setting."""
    system_config = session.get(SystemConfig, "default_cooldown_minutes")
    return int(system_config.value) if system_config else 15


def get_global_cache_media(session: Session) -> bool:
    """Return the global default cache_media setting."""
    system_config = session.get(SystemConfig, "cache_media")
    return system_config.value == "true" if system_config else False


def get_base_url(session: Session) -> str:
    """Return the global base_url setting."""
    system_config = session.get(SystemConfig, "base_url")
    return system_config.value if system_config else "http://localhost:8000"


def save_system_config(key: str, value: str | None, session: Session) -> None:
    if value is not None:
        session.merge(SystemConfig(key=key, value=value))


def save_feed(feed_config: FeedConfigBase, session: Session) -> Feed:
    """Persist a single feed config to the database.

    Creates or updates the Feed row, then rebuilds its FeedRelationship
    (for digest/smart_filter) and FeedTag associations.
    Returns the saved Feed object.
    """
    existing = session.get(Feed, feed_config.id)
    if existing:
        existing.type = feed_config.type
        existing.name = feed_config.name
        existing.limit = feed_config.limit
        existing.cache_media = feed_config.cache_media
        existing.cooldown_minutes = feed_config.cooldown_minutes
        existing.enabled = feed_config.enabled
        existing.config = feed_config.extra_config()
        db_feed = existing
        session.add(db_feed)
    else:
        db_feed = Feed(
            id=feed_config.id,
            type=feed_config.type,
            name=feed_config.name,
            limit=feed_config.limit,
            cache_media=feed_config.cache_media,
            cooldown_minutes=feed_config.cooldown_minutes,
            enabled=feed_config.enabled,
            config=feed_config.extra_config(),
            updated_at=None,
        )
        session.add(db_feed)

    session.flush()

    # Rebuild FeedRelationship for digest/smart_filter
    for rel in session.exec(
        select(FeedRelationship).where(
            FeedRelationship.parent_feed_id == feed_config.id
        )
    ).all():
        session.delete(rel)

    if isinstance(
        feed_config, (DigestFeedHandler.Config, SmartFilterFeedHandler.Config)
    ):
        session.add(
            FeedRelationship(
                parent_feed_id=feed_config.id,
                child_feed_id=feed_config.source,
                position=0,
            )
        )

    # Rebuild FeedTag associations
    session.exec(
        text("DELETE FROM feed_tag WHERE feed_id = :fid"),
        params={"fid": feed_config.id},
    )

    if feed_config.tags:
        existing_tags = {t.name: t for t in session.exec(select(Tag)).all()}
        new_tags = [Tag(name=n) for n in feed_config.tags if n not in existing_tags]
        if new_tags:
            for t in new_tags:
                session.add(t)
            session.flush()
            for t in new_tags:
                session.refresh(t)
                existing_tags[t.name] = t
        for tag_name in feed_config.tags:
            session.add(
                FeedTag(feed_id=feed_config.id, tag_id=existing_tags[tag_name].id)
            )

    session.commit()
    session.refresh(db_feed)
    return db_feed


def upsert_feed(
    form_data: dict,
    session: Session,
    *,
    existing_feed_id: str | None = None,
) -> tuple[Feed | None, dict[str, str]]:
    """Validate form data and persist a feed (create or update).

    Args:
        form_data: Raw dict from the submitted form (all values are strings).
        session: Database session.
        existing_feed_id: Set when editing; prevents id changes from silently
            creating a new feed instead of updating.

    Returns:
        (Feed, {}) on success, or (None, {field: error_message, ...}) on failure.

    The caller is responsible for ensuring the feed type is present in form_data["type"].
    Empty string values for Optional fields are coerced to None before validation.
    """
    from pydantic import ValidationError

    feed_type = form_data.get("type", "")
    try:
        handler_cls = FeedRegistry.get_handler(feed_type)
    except ValueError:
        return None, {"type": f"Unknown feed type: {feed_type!r}"}

    config_cls = handler_cls.Config

    optional_fields = {"cache_media", "cooldown_minutes", "schedule"}
    coerced: dict = {}
    for key, val in form_data.items():
        if val == "" and key in optional_fields:
            coerced[key] = None
        else:
            coerced[key] = val

    raw_tags = coerced.get("tags", "")
    if isinstance(raw_tags, str):
        coerced["tags"] = [t.strip() for t in raw_tags.split(",") if t.strip()]

    raw_include_tags = coerced.get("include_tags", "")
    if isinstance(raw_include_tags, str):
        coerced["include_tags"] = [
            t.strip() for t in raw_include_tags.split(",") if t.strip()
        ]

    raw_strip_tags = coerced.get("strip_tags", "")
    if isinstance(raw_strip_tags, str):
        coerced["strip_tags"] = [
            t.strip().lower() for t in raw_strip_tags.split(",") if t.strip()
        ]

    coerced["strip_tags_enabled"] = coerced.get("strip_tags_enabled") == "true"

    if "cache_media" in coerced and coerced["cache_media"] in ("true", "false"):
        coerced["cache_media"] = coerced["cache_media"] == "true"

    coerced["enabled"] = coerced.get("enabled") == "true"

    if existing_feed_id is not None:
        coerced["id"] = existing_feed_id

    if existing_feed_id is None:
        candidate_id = coerced.get("id", "")
        if session.get(Feed, candidate_id):
            return None, {"id": f"A feed with id '{candidate_id}' already exists."}

    try:
        feed_config = config_cls.model_validate(coerced)
    except ValidationError as e:
        errors: dict[str, str] = {}
        for err in e.errors():
            loc = err["loc"]
            field = str(loc[-1]) if loc else "__all__"
            errors.setdefault(field, err["msg"])
        return None, errors

    if isinstance(
        feed_config, (DigestFeedHandler.Config, SmartFilterFeedHandler.Config)
    ):
        source_id = feed_config.source
        if not session.get(Feed, source_id):
            return None, {"source": f"Source feed '{source_id}' does not exist."}

    feed = save_feed(feed_config, session)
    return feed, {}


def get_current_config(session: Session) -> dict:
    """Reconstruct system config from database."""
    keys = {
        "cache_media",
        "default_cooldown_minutes",
        "base_url",
        "scrape_creators_key",
        "anthropic_api_key",
        "imap_host",
        "imap_port",
        "imap_user",
        "imap_password",
        "imap_folder",
        "imap_lookback_days",
        "imap_max_message_bytes",
        "reddit_session_token",
    }
    rows = {
        c.key: c.value
        for c in session.exec(
            select(SystemConfig).where(col(SystemConfig.key).in_(keys))
        ).all()
    }
    return {
        "cache_media": rows.get("cache_media") == "true",
        "default_cooldown_minutes": int(rows.get("default_cooldown_minutes", "15")),
        "base_url": rows.get("base_url", "http://localhost:8000"),
        "scrape_creators_key": rows.get("scrape_creators_key"),
        "anthropic_api_key": rows.get("anthropic_api_key"),
        "imap_host": rows.get("imap_host"),
        "imap_port": int(rows.get("imap_port", "993")),
        "imap_user": rows.get("imap_user"),
        "imap_password": rows.get("imap_password"),
        "imap_folder": rows.get("imap_folder", "INBOX"),
        "imap_lookback_days": int(rows.get("imap_lookback_days", "7")),
        "imap_max_message_bytes": int(
            rows.get("imap_max_message_bytes", str(2 * 1024 * 1024))
        ),
        "reddit_session_token": rows.get("reddit_session_token"),
    }
