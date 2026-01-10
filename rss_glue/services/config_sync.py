"""JSON config to database synchronization."""
from datetime import datetime

from sqlmodel import Session, select

from rss_glue.models.config import (
    AppConfig,
    RssFeedConfig,
    MergeFeedConfig,
    DigestFeedConfig,
    HackerNewsFeedConfig,
    InstagramFeedConfig,
    FacebookFeedConfig,
    RedditFeedConfig,
)
from rss_glue.models.db import Feed, FeedRelationship, SystemConfig


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

        # Build config dict based on feed type
        config_dict: dict = {}
        
        # Store explicit cache_media setting if present
        if feed_config.cache_media is not None:
            config_dict["cache_media_explicit"] = feed_config.cache_media

        if isinstance(feed_config, RssFeedConfig):
            config_dict["url"] = feed_config.url
        elif isinstance(feed_config, DigestFeedConfig):
            config_dict["schedule"] = feed_config.schedule
        elif isinstance(feed_config, HackerNewsFeedConfig):
            config_dict["story_type"] = feed_config.story_type
        elif isinstance(feed_config, InstagramFeedConfig):
            config_dict.update({
                "username": feed_config.username,
            })
        elif isinstance(feed_config, FacebookFeedConfig):
            config_dict.update({
                "url": feed_config.url,
            })
        elif isinstance(feed_config, RedditFeedConfig):
            config_dict.update({
                "subreddit": feed_config.subreddit,
                "listing_type": feed_config.listing_type,
                "time_filter": feed_config.time_filter,
            })

        if feed_config.id in existing_feeds:
            # Update existing
            db_feed = existing_feeds[feed_config.id]
            db_feed.type = feed_config.type
            db_feed.name = feed_config.name
            db_feed.limit = feed_config.limit
            db_feed.cache_media = cache_media
            db_feed.config = config_dict
            db_feed.updated_at = datetime.utcnow()

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
                config=config_dict,
            )
            session.add(db_feed)
            stats["feeds_created"] += 1

    session.commit()

    # Clear all existing relationships
    for rel in session.exec(select(FeedRelationship)).all():
        session.delete(rel)
    session.commit()

    # Create relationships for merge and digest feeds
    for feed_config in config.feeds:
        if isinstance(feed_config, MergeFeedConfig):
            for i, source_id in enumerate(feed_config.sources):
                rel = FeedRelationship(
                    parent_feed_id=feed_config.id,
                    child_feed_id=source_id,
                    position=i,
                )
                session.add(rel)
                stats["relationships_updated"] += 1
        elif isinstance(feed_config, DigestFeedConfig):
            # Digest feeds have a single source
            rel = FeedRelationship(
                parent_feed_id=feed_config.id,
                child_feed_id=feed_config.source,
                position=0,
            )
            session.add(rel)
            stats["relationships_updated"] += 1

    session.commit()
    return stats


def get_current_config(session: Session) -> dict:
    """Reconstruct JSON config from database."""
    # Get global config
    system_config_media = session.get(SystemConfig, "cache_media")
    global_cache_media = system_config_media.value == "true" if system_config_media else False
    
    system_config_key = session.get(SystemConfig, "scrape_creators_key")
    scrape_creators_key = system_config_key.value if system_config_key else None
    
    feeds = session.exec(select(Feed)).all()
    config: dict = {
        "cache_media": global_cache_media,
        "feeds": []
    }
    
    if scrape_creators_key:
        config["scrape_creators_key"] = scrape_creators_key

    for feed in feeds:
        feed_dict = {
            "id": feed.id,
            "type": feed.type,
            "name": feed.name,
            "limit": feed.limit,
        }
        
        # Restore explicit cache_media setting
        if feed.config.get("cache_media_explicit") is not None:
            feed_dict["cache_media"] = feed.config["cache_media_explicit"]

        if feed.type == "rss":
            feed_dict["url"] = feed.config.get("url", "")
        elif feed.type == "merge":
            # Get source IDs
            rels = session.exec(
                select(FeedRelationship)
                .where(FeedRelationship.parent_feed_id == feed.id)
                .order_by(FeedRelationship.position)
            ).all()
            sources = [r.child_feed_id for r in rels]
            feed_dict["sources"] = sources
        elif feed.type == "digest":
            # Get source ID (digest has a single source)
            rel = session.exec(
                select(FeedRelationship).where(
                    FeedRelationship.parent_feed_id == feed.id
                )
            ).first()
            source = rel.child_feed_id if rel else ""
            feed_dict["source"] = source
            feed_dict["schedule"] = feed.config.get("schedule", "")
        elif feed.type == "hackernews":
            feed_dict["story_type"] = feed.config.get("story_type", "top")
        elif feed.type == "instagram":
            feed_dict["username"] = feed.config.get("username", "")
        elif feed.type == "facebook":
            feed_dict["url"] = feed.config.get("url", "")
        elif feed.type == "reddit":
            feed_dict["subreddit"] = feed.config.get("subreddit", "")
            feed_dict["listing_type"] = feed.config.get("listing_type", "top")
            feed_dict["time_filter"] = feed.config.get("time_filter", "day")

        config["feeds"].append(feed_dict)

    return config
