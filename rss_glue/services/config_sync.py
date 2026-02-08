"""JSON config to database synchronization."""

from rss_glue.feeds.smart_filter import SmartFilterFeedHandler
from rss_glue.feeds.digest import DigestFeedHandler

from sqlalchemy import text
from sqlmodel import Session, select

from rss_glue.feeds import FeedRegistry
from rss_glue.models.config import AppConfig
from rss_glue.models.db import Feed, FeedRelationship, FeedTag, SystemConfig, Tag


def sync_config_to_db(config: AppConfig, session: Session) -> dict:
    """Synchronize JSON config to database.

    Returns dict with sync stats:
    - feeds_created: int
    - feeds_updated: int
    - feeds_deleted: int
    - relationships_updated: int
    """
    stats = {
        "feeds_created": 0,
        "feeds_updated": 0,
        "feeds_deleted": 0,
        "relationships_updated": 0,
    }

    # Save global config
    system_config_media = session.get(SystemConfig, "cache_media")
    if not system_config_media:
        system_config_media = SystemConfig(
            key="cache_media", value=str(config.cache_media).lower()
        )
        session.add(system_config_media)
    else:
        system_config_media.value = str(config.cache_media).lower()
        session.add(system_config_media)

    # Save ScrapeCreators key
    if config.scrape_creators_key:
        system_config_key = session.get(SystemConfig, "scrape_creators_key")
        if not system_config_key:
            system_config_key = SystemConfig(
                key="scrape_creators_key", value=config.scrape_creators_key
            )
            session.add(system_config_key)
        else:
            system_config_key.value = config.scrape_creators_key
            session.add(system_config_key)
    else:
        # If None, remove it or leave it? Safer to remove if explicitly None,
        # but user might leave it out of JSON to keep existing.
        # However, AppConfig defaults it to None.
        # Let's assume if it is in config it should be synced.
        # But if it is None in input, maybe we should delete it?
        # Actually, let's keep it simple: if provided, update. If not provided (None), do nothing (or delete?).
        # Given this is a full config sync, we should probably match the state.
        pass

    # Save Anthropic API key
    if config.anthropic_api_key:
        system_config_anthropic = session.get(SystemConfig, "anthropic_api_key")
        if not system_config_anthropic:
            system_config_anthropic = SystemConfig(
                key="anthropic_api_key", value=config.anthropic_api_key
            )
            session.add(system_config_anthropic)
        else:
            system_config_anthropic.value = config.anthropic_api_key
            session.add(system_config_anthropic)

    # Save default cooldown
    system_config_cooldown = session.get(SystemConfig, "default_cooldown_minutes")
    if not system_config_cooldown:
        system_config_cooldown = SystemConfig(
            key="default_cooldown_minutes", value=str(config.default_cooldown_minutes)
        )
        session.add(system_config_cooldown)
    else:
        system_config_cooldown.value = str(config.default_cooldown_minutes)
        session.add(system_config_cooldown)

    # Save base URL
    system_config_base_url = session.get(SystemConfig, "base_url")
    if not system_config_base_url:
        system_config_base_url = SystemConfig(key="base_url", value=config.base_url)
        session.add(system_config_base_url)
    else:
        system_config_base_url.value = config.base_url
        session.add(system_config_base_url)

    config_feed_ids = {feed.id for feed in config.feeds}

    # Get existing feeds
    existing_feeds = {f.id: f for f in session.exec(select(Feed)).all()}

    # Delete feeds not in config
    for feed_id, feed in existing_feeds.items():
        if feed_id not in config_feed_ids:
            session.delete(feed)
            stats["feeds_deleted"] += 1

    # Create/update feeds from config
    for feed_config in config.feeds:
        # Determine cache_media setting
        # Use per-feed setting if set, otherwise use global setting
        if feed_config.cache_media is not None:
            cache_media = feed_config.cache_media
        else:
            cache_media = config.cache_media

        # Determine cooldown_minutes setting
        # Use per-feed setting if set, otherwise use global setting
        if feed_config.cooldown_minutes is not None:
            cooldown_minutes = feed_config.cooldown_minutes
        else:
            cooldown_minutes = config.default_cooldown_minutes

        if feed_config.id in existing_feeds:
            # Update existing
            db_feed = existing_feeds[feed_config.id]
            db_feed.type = feed_config.type
            db_feed.name = feed_config.name
            db_feed.limit = feed_config.limit
            db_feed.cache_media = cache_media
            db_feed.cooldown_minutes = cooldown_minutes
            db_feed.enabled = feed_config.enabled
            db_feed.config = feed_config.extra_config()

            session.add(db_feed)
            stats["feeds_updated"] += 1
        else:
            # Create new
            db_feed = Feed(
                id=feed_config.id,
                type=feed_config.type,
                name=feed_config.name,
                limit=feed_config.limit,
                cache_media=cache_media,
                cooldown_minutes=cooldown_minutes,
                enabled=feed_config.enabled,
                config=feed_config.extra_config(),
                updated_at=None,  # Will be set when first updated
            )
            session.add(db_feed)
            stats["feeds_created"] += 1

    session.commit()

    # Clear all existing relationships and tags
    for rel in session.exec(select(FeedRelationship)).all():
        session.delete(rel)
    session.exec(text("DELETE FROM feed_tag"))
    session.commit()

    # Create relationships for digest and smart_filter feeds (merge feeds use tags instead)
    for feed_config in config.feeds:
        if isinstance(
            feed_config, (DigestFeedHandler.Config, SmartFilterFeedHandler.Config)
        ):
            rel = FeedRelationship(
                parent_feed_id=feed_config.id,
                child_feed_id=feed_config.source,
                position=0,
            )
            session.add(rel)
            stats["relationships_updated"] += 1

    # Sync tags
    existing_tags = {t.name: t for t in session.exec(select(Tag)).all()}
    for feed_config in config.feeds:
        if feed_config.tags:
            for tag_name in feed_config.tags:
                if tag_name not in existing_tags:
                    new_tag = Tag(name=tag_name)
                    session.add(new_tag)
                    session.flush()
                    session.refresh(new_tag)
                    existing_tags[tag_name] = new_tag

                tag_obj = existing_tags[tag_name]
                # Check if link exists? No, we cleared all feed_tags
                session.add(FeedTag(feed_id=feed_config.id, tag_id=tag_obj.id))

    session.commit()
    return stats


def get_current_config(session: Session) -> dict:
    """Reconstruct JSON config from database."""
    # Get global config
    system_config_media = session.get(SystemConfig, "cache_media")
    global_cache_media = (
        system_config_media.value == "true" if system_config_media else False
    )

    system_config_key = session.get(SystemConfig, "scrape_creators_key")
    scrape_creators_key = system_config_key.value if system_config_key else None

    system_config_cooldown = session.get(SystemConfig, "default_cooldown_minutes")
    default_cooldown_minutes = (
        int(system_config_cooldown.value) if system_config_cooldown else 15
    )

    system_config_base_url = session.get(SystemConfig, "base_url")
    base_url = (
        system_config_base_url.value
        if system_config_base_url
        else "http://localhost:8000"
    )

    system_config_anthropic = session.get(SystemConfig, "anthropic_api_key")
    anthropic_api_key = (
        system_config_anthropic.value if system_config_anthropic else None
    )

    feeds = session.exec(select(Feed)).all()
    config: dict = {
        "cache_media": global_cache_media,
        "default_cooldown_minutes": default_cooldown_minutes,
        "base_url": base_url,
        "feeds": [],
    }

    if scrape_creators_key:
        config["scrape_creators_key"] = scrape_creators_key

    if anthropic_api_key:
        config["anthropic_api_key"] = anthropic_api_key

    for feed in feeds:
        feed_config_cls = FeedRegistry.get_handler(feed.type).Config
        feed_dict = feed_config_cls.db_hydrate(feed, session=session).model_dump(
            exclude_none=True
        )
        if len(feed_dict.get("tags", [])) == 0:
            del feed_dict["tags"]  # Don't include empty tags list in config

        config["feeds"].append(feed_dict)

    return config
