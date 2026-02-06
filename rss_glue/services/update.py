"""Feed update orchestration with topological sort."""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from rss_glue.feeds.registry import FeedRegistry
from rss_glue.models.db import (
    Enclosure,
    Feed,
    FeedRelationship,
    MediaCache,
    Post,
    UpdateHistory,
)
from rss_glue.services.media_cache import cache_enclosure, process_post_media


def topological_sort_feeds(session: Session) -> list[str]:
    """Return feed IDs in topological order (dependencies first).

    For update order: source feeds must be updated before merge/digest feeds.
    Uses Kahn's algorithm.
    """
    from rss_glue.feeds.merge import get_merge_source_ids

    # Get all feeds
    feeds = {f.id: f for f in session.exec(select(Feed)).all()}

    if not feeds:
        return []

    # Build dependency graph
    # For update order, parent (merge/digest) depends on children (sources)
    deps: dict[str, set[str]] = defaultdict(set)

    # Get digest dependencies from FeedRelationship
    for rel in session.exec(select(FeedRelationship)).all():
        deps[rel.parent_feed_id].add(rel.child_feed_id)

    # Get merge dependencies from tags
    for feed_id, feed in feeds.items():
        if feed.type == "merge":
            deps[feed_id] = get_merge_source_ids(feed_id, session)

    # Initialize in-degree for all feeds
    in_degree: dict[str, int] = {feed_id: 0 for feed_id in feeds}
    for parent, children in deps.items():
        in_degree[parent] = len(children)

    # Start with feeds that have no dependencies (in_degree = 0)
    queue = [fid for fid in feeds if in_degree[fid] == 0]
    result = []

    while queue:
        feed_id = queue.pop(0)
        result.append(feed_id)

        # Find feeds that depend on this one and decrement their in-degree
        for parent, children in deps.items():
            if feed_id in children:
                in_degree[parent] -= 1
                if in_degree[parent] == 0:
                    queue.append(parent)

    return result


def update_feed(
    feed_id: str,
    session: Session,
    force: bool = False,
) -> Optional[UpdateHistory]:
    """Update a single feed.

    Args:
        feed_id: ID of the feed to update
        session: Database session
        force: If True, bypass cooldown check and update immediately
    """
    feed = session.get(Feed, feed_id)
    if not feed:
        raise ValueError(f"Feed not found: {feed_id}")

    # Skip disabled feeds
    if not feed.enabled:
        return None

    # Merge is a special case - no updates
    if feed.type == "merge":
        return None

    # Check if update is due (skip if not forced and next_update is in the future)
    if not force:
        handler = FeedRegistry.get_handler(feed.type)
        next_update = handler.next_update(feed, session)
        if next_update is not None and datetime.now(timezone.utc) < next_update:
            return None

    # Create update history record
    history = UpdateHistory(feed_id=feed_id)
    session.add(history)
    session.commit()
    session.refresh(history)

    try:
        handler = FeedRegistry.get_handler(feed.type)

        # Fetch posts from source
        config_with_limit = {**feed.config, "limit": feed.limit}
        result = handler.fetch(feed_id, config_with_limit, session)
        posts_added = 0
        posts_data: list[dict] = []

        if result is None:
            return None  # Short circuit if no work was done.
        elif isinstance(result, int):
            posts_added = result
        else:
            posts_data = result

        new_posts = []
        new_post_enclosures: list[tuple[Post, list[dict]]] = []
        for post_data in posts_data:
            # Check if post already exists
            existing = session.exec(
                select(Post).where(
                    Post.feed_id == feed_id,
                    Post.external_id == post_data["external_id"],
                )
            ).first()

            if not existing:
                # Extract enclosures before creating Post (not a column field)
                enclosures_data = post_data.pop("enclosures", [])
                post = Post(feed_id=feed_id, **post_data)
                session.add(post)
                session.flush()  # Get the post ID
                new_posts.append(post)
                if enclosures_data:
                    new_post_enclosures.append((post, enclosures_data))
                posts_added += 1

            elif post_data.get("score"):
                # Update score for existing post if provided
                # Helpful because scores generally go up over time.
                existing.score = post_data["score"]
                session.add(existing)

        # Create enclosure records for new posts
        for post, enclosures_data in new_post_enclosures:
            for enc_data in enclosures_data:
                if not enc_data.get("url"):
                    continue
                enclosure = Enclosure(
                    post_id=post.id,
                    url=enc_data["url"],
                    original_url=enc_data["url"],
                    mime_type=enc_data.get("mime_type"),
                    length=enc_data.get("length"),
                )
                session.add(enclosure)
                session.flush()

                # Cache enclosure if media caching is enabled
                if feed.cache_media:
                    cache_enclosure(enclosure, session)

        # Process media caching for new posts if enabled
        if feed.cache_media and new_posts:
            for post in new_posts:
                new_content = process_post_media(post, session)
                if new_content != post.content:
                    post.content = new_content
                    session.add(post)

        history.status = "success"
        history.posts_added = posts_added
        history.completed_at = datetime.now(timezone.utc)

        # Update feed's updated_at
        feed.updated_at = datetime.now(timezone.utc)
        session.add(feed)

    except Exception as e:
        history.status = "error"
        history.error_message = str(e)
        history.completed_at = datetime.now(timezone.utc)
        feed.enabled = False  # Disable feed on error
        session.add(feed)

    session.add(history)
    session.commit()
    return history


def update_all_feeds(
    session: Session,
    force: bool = False,
) -> list[UpdateHistory]:
    """Update all feeds in topological order.

    Args:
        session: Database session
        force: If True, bypass cooldown check for all feeds
    """
    feed_order = topological_sort_feeds(session)
    results = []

    for feed_id in feed_order:
        history = update_feed(feed_id, session, force)
        if history:
            results.append(history)

    return results


def reset_feed(
    feed_id: str,
    session: Session,
) -> dict[str, int]:
    """Reset a feed to its initial state.

    Removes all posts, media cache, update history, and physical media files.

    Args:
        feed_id: ID of the feed to reset
        session: Database session

    Returns:
        Dict with counts of deleted items

    Raises:
        ValueError: If feed not found
    """
    from rss_glue.services.media_cache import MEDIA_DIR

    feed = session.get(Feed, feed_id)
    if not feed:
        raise ValueError(f"Feed not found: {feed_id}")

    # Get media cache entries before deleting (for file cleanup)
    media_entries = list(
        session.exec(select(MediaCache).where(MediaCache.feed_id == feed_id)).all()
    )

    # Get enclosure entries with local_path before deleting (for file cleanup)
    posts = list(session.exec(select(Post).where(Post.feed_id == feed_id)).all())
    post_ids = [p.id for p in posts if p.id is not None]
    enclosure_paths = []
    if post_ids:
        enclosures = list(
            session.exec(select(Enclosure).where(Enclosure.post_id.in_(post_ids))).all()  # type: ignore[union-attr]
        )
        enclosure_paths = [e.local_path for e in enclosures if e.local_path]

    # Use handler to reset feed-specific data (posts, digest issues, etc.)
    handler = FeedRegistry.get_handler(feed.type)
    counts = handler.reset(feed_id, session)

    # Delete update history for all feed types
    history_entries = list(
        session.exec(
            select(UpdateHistory).where(UpdateHistory.feed_id == feed_id)
        ).all()
    )
    for entry in history_entries:
        session.delete(entry)
    counts["history_deleted"] = len(history_entries)

    # Reset updated_at
    feed.updated_at = None
    session.add(feed)
    session.commit()

    # Delete physical media files (from MediaCache and Enclosures)
    files_deleted = 0
    all_paths = [media.local_path for media in media_entries] + enclosure_paths
    for local_path in all_paths:
        file_path = MEDIA_DIR / local_path
        if file_path.exists():
            try:
                file_path.unlink()
                files_deleted += 1
                # Try to remove empty parent directory
                parent = file_path.parent
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass  # Ignore file deletion errors
    counts["files_deleted"] = files_deleted

    return counts
