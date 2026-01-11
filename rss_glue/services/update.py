"""Feed update orchestration with topological sort."""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from rss_glue.feeds.registry import FeedRegistry
from rss_glue.models.db import (
    DigestIssue,
    Feed,
    FeedRelationship,
    MediaCache,
    Post,
    UpdateHistory,
)
from rss_glue.services.cooldown import should_update_feed
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

    # Check cooldown before updating
    should_update, next_update_time, reason = should_update_feed(feed, force)
    if not should_update:
        return None

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
            history.completed_at = datetime.now(timezone.utc)
            session.add(history)
            session.commit()
            return history

        # Digest feeds create issues from source feed posts
        if feed.type == "digest":
            config_with_limit = {**feed.config, "limit": feed.limit}
            handler.fetch(feed_id, config_with_limit, session)
            history.status = "success"
            history.completed_at = datetime.now(timezone.utc)
            feed.updated_at = datetime.now(timezone.utc)
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
    For merge feeds: only clears history (doesn't own posts).
    For digest feeds: clears digest issues but not source posts.

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

    counts = {
        "posts_deleted": 0,
        "media_deleted": 0,
        "history_deleted": 0,
        "digest_issues_deleted": 0,
        "files_deleted": 0,
    }

    # Get media cache entries before deleting (for file cleanup)
    media_entries = list(
        session.exec(select(MediaCache).where(MediaCache.feed_id == feed_id)).all()
    )

    if feed.type == "merge":
        # Merge feeds don't own posts, only clear history
        pass

    elif feed.type == "digest":
        # Delete digest issues (cascades to DigestIssuePost)
        digest_issues = list(
            session.exec(
                select(DigestIssue).where(DigestIssue.feed_id == feed_id)
            ).all()
        )
        for issue in digest_issues:
            session.delete(issue)
        counts["digest_issues_deleted"] = len(digest_issues)

    else:
        # Regular feeds: delete posts (cascades to MediaCache via relationship)
        posts = list(session.exec(select(Post).where(Post.feed_id == feed_id)).all())
        for post in posts:
            session.delete(post)
        counts["posts_deleted"] = len(posts)
        counts["media_deleted"] = len(media_entries)

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

    # Delete physical media files
    for media in media_entries:
        file_path = MEDIA_DIR / media.local_path
        if file_path.exists():
            try:
                file_path.unlink()
                counts["files_deleted"] += 1
                # Try to remove empty parent directory
                parent = file_path.parent
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass  # Ignore file deletion errors

    return counts
