"""Feed update orchestration with topological sort."""
from collections import defaultdict
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from rss_glue.models.db import Feed, FeedRelationship, Post, UpdateHistory
from rss_glue.feeds.registry import FeedRegistry
from rss_glue.services.media_cache import process_post_media


def topological_sort_feeds(session: Session) -> list[str]:
    """Return feed IDs in topological order (dependencies first).

    For update order: source feeds must be updated before merge feeds.
    Uses Kahn's algorithm.
    """
    # Get all feeds
    feeds = {f.id: f for f in session.exec(select(Feed)).all()}

    if not feeds:
        return []

    # Build dependency graph
    # For update order, parent (merge) depends on children (sources)
    deps: dict[str, set[str]] = defaultdict(set)
    for rel in session.exec(select(FeedRelationship)).all():
        deps[rel.parent_feed_id].add(rel.child_feed_id)

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
    base_url: Optional[str] = None,
) -> UpdateHistory:
    """Update a single feed.

    Args:
        feed_id: ID of the feed to update
        session: Database session
        base_url: Base URL for media caching (required if caching enabled)
    """
    feed = session.get(Feed, feed_id)
    if not feed:
        raise ValueError(f"Feed not found: {feed_id}")

    # Create update history record
    history = UpdateHistory(feed_id=feed_id)
    session.add(history)
    session.commit()
    session.refresh(history)

    try:
        handler = FeedRegistry.get_handler(feed.type)

        # Merge feeds don't fetch external data
        if feed.type == "merge":
            history.status = "success"
            history.completed_at = datetime.utcnow()
            session.add(history)
            session.commit()
            return history

        # Digest feeds create issues from source feed posts
        if feed.type == "digest":
            config_with_limit = {**feed.config, "limit": feed.limit}
            handler.fetch(feed_id, config_with_limit, session)
            history.status = "success"
            history.completed_at = datetime.utcnow()
            feed.updated_at = datetime.utcnow()
            session.add(feed)
            session.add(history)
            session.commit()
            return history

        # Fetch posts from source
        config_with_limit = {**feed.config, "limit": feed.limit}
        posts_data = handler.fetch(feed_id, config_with_limit, session)

        posts_added = 0
        new_posts = []
        for post_data in posts_data:
            # Check if post already exists
            existing = session.exec(
                select(Post).where(
                    Post.feed_id == feed_id,
                    Post.external_id == post_data["external_id"],
                )
            ).first()

            if not existing:
                post = Post(feed_id=feed_id, **post_data)
                session.add(post)
                session.flush()  # Get the post ID
                new_posts.append(post)
                posts_added += 1

        # Process media caching for new posts if enabled
        if feed.cache_media and base_url and new_posts:
            for post in new_posts:
                new_content = process_post_media(post, session, base_url)
                if new_content != post.content:
                    post.content = new_content
                    session.add(post)

        history.status = "success"
        history.posts_added = posts_added
        history.completed_at = datetime.utcnow()

        # Update feed's updated_at
        feed.updated_at = datetime.utcnow()
        session.add(feed)

    except Exception as e:
        history.status = "error"
        history.error_message = str(e)
        history.completed_at = datetime.utcnow()

    session.add(history)
    session.commit()
    return history


def update_all_feeds(
    session: Session,
    base_url: Optional[str] = None,
) -> list[UpdateHistory]:
    """Update all feeds in topological order.

    Args:
        session: Database session
        base_url: Base URL for media caching (required if caching enabled)
    """
    feed_order = topological_sort_feeds(session)
    results = []

    for feed_id in feed_order:
        history = update_feed(feed_id, session, base_url)
        results.append(history)

    return results
