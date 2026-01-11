"""Background worker for automatic feed updates."""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from croniter import croniter
from sqlmodel import Session, select

from rss_glue.database import engine
from rss_glue.models.db import Feed, FeedRelationship
from rss_glue.services.update import topological_sort_feeds, update_feed

logger = logging.getLogger("rss_glue.background_worker")

# Global worker state
_worker_task: Optional[asyncio.Task] = None
_shutdown_event: Optional[asyncio.Event] = None


def calculate_next_update(feed: Feed, session: Session) -> Optional[datetime]:
    """Calculate when feed should next update. Returns None for manual-only feeds."""
    # Merge feeds always update (no cooldown)
    if feed.type == "merge":
        return datetime.now(timezone.utc)

    # Digest feeds use cron schedule
    if feed.type == "digest":
        schedule = feed.config.get("schedule")
        if not schedule:
            return None  # Manual-only

        try:
            # If never updated, calculate from one period ago
            if feed.updated_at is None:
                base_time = datetime.now(timezone.utc)
                cron = croniter(schedule, base_time)
                cron.get_prev(datetime)  # Go back one period
                start_time = cron.get_prev(datetime)  # And one more to get start
                cron = croniter(schedule, start_time)
            else:
                cron = croniter(schedule, feed.updated_at)

            next_time = cron.get_next(datetime)
            # Ensure timezone-aware
            if next_time.tzinfo is None:
                next_time = next_time.replace(tzinfo=timezone.utc)
            return next_time
        except (ValueError, KeyError) as e:
            logger.warning(f"Invalid cron schedule for feed {feed.id}: {e}")
            return None  # Manual-only if invalid

    # Regular feeds use cooldown_minutes
    if feed.cooldown_minutes is None or feed.cooldown_minutes <= 0:
        return None  # Manual-only

    if feed.updated_at is None:
        # Never updated - schedule immediately
        return datetime.now(timezone.utc)

    # Calculate next update from last update time
    from datetime import timedelta

    return feed.updated_at + timedelta(minutes=feed.cooldown_minutes)


def get_feed_dependencies(feed_id: str, session: Session) -> list[str]:
    """Recursively get all dependencies of a feed.

    Returns list of feed IDs that this feed depends on (children/sources).
    """
    stmt = select(FeedRelationship.child_feed_id).where(
        FeedRelationship.parent_feed_id == feed_id
    )
    children = list(session.exec(stmt).all())

    result = []
    for child_id in children:
        result.append(child_id)
        # Recursively get dependencies of dependencies
        result.extend(get_feed_dependencies(child_id, session))

    return result


def get_feeds_to_update(session: Session) -> list[str]:
    """Get feeds to update (due + dependencies) in topological order.

    Returns list of feed IDs to update, in dependency order.
    """
    now = datetime.now(timezone.utc)
    feeds_to_update = set()

    # Find all feeds that are due for update
    all_feeds = session.exec(select(Feed)).all()
    for feed in all_feeds:
        next_update = calculate_next_update(feed, session)
        if next_update and next_update <= now:
            # This feed is due - add it and all its dependencies
            feeds_to_update.add(feed.id)
            dependencies = get_feed_dependencies(feed.id, session)
            feeds_to_update.update(dependencies)

    if not feeds_to_update:
        return []

    # Get topological order of all feeds
    all_feed_order = topological_sort_feeds(session)

    # Filter to only feeds we want to update, preserving order
    return [fid for fid in all_feed_order if fid in feeds_to_update]


def calculate_next_wake_time(session: Session) -> Optional[datetime]:
    """Calculate earliest next_update across all feeds.

    Returns None if no feeds have scheduled updates.
    """
    all_feeds = session.exec(select(Feed)).all()
    next_times = []

    for feed in all_feeds:
        next_update = calculate_next_update(feed, session)
        if next_update:
            next_times.append(next_update)

    return min(next_times) if next_times else None


async def run_update_cycle(shutdown_event: asyncio.Event) -> int:
    """Run one update cycle. Returns number of feeds updated."""

    def _sync_update_cycle():
        with Session(engine) as session:
            feeds_to_update = get_feeds_to_update(session)

            if not feeds_to_update:
                return 0

            logger.info(f"Updating {len(feeds_to_update)} feeds: {feeds_to_update}")

            updated_count = 0
            for feed_id in feeds_to_update:
                if shutdown_event.is_set():
                    logger.info("Shutdown requested during update cycle")
                    break

                try:
                    history = update_feed(feed_id, session, force=True)
                    if history:
                        updated_count += 1
                        if history.status == "success":
                            logger.info(
                                f"Updated feed {feed_id}: {history.posts_added} posts added"
                            )
                        else:
                            logger.error(
                                f"Feed {feed_id} update failed: {history.error_message}"
                            )
                except ValueError as e:
                    # Feed not found (deleted while worker running)
                    logger.warning(f"Feed {feed_id} not found: {e}")
                except Exception as e:
                    logger.error(f"Error updating feed {feed_id}: {e}", exc_info=True)

            return updated_count

    # Run DB operations in thread (SQLModel is sync)
    return await asyncio.to_thread(_sync_update_cycle)


async def background_worker_loop(shutdown_event: asyncio.Event):
    """Main worker loop."""
    logger.info("Background worker started")

    while not shutdown_event.is_set():
        try:
            # Run update cycle
            updated_count = await run_update_cycle(shutdown_event)

            if updated_count > 0:
                logger.info(f"Update cycle completed: {updated_count} feeds updated")

            # Calculate next wake time
            def _get_next_wake():
                with Session(engine) as session:
                    return calculate_next_wake_time(session)

            next_wake = await asyncio.to_thread(_get_next_wake)

            if next_wake:
                now = datetime.now(timezone.utc)
                sleep_seconds = (next_wake - now).total_seconds()
                if sleep_seconds < 0:
                    sleep_seconds = 0
                logger.info(
                    f"Next update at {next_wake.isoformat()}, sleeping for {sleep_seconds:.0f}s"
                )
            else:
                sleep_seconds = 300  # 5 minutes default
                logger.info("No scheduled updates, sleeping for 5 minutes")

            # Sleep until next wake or shutdown
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(), timeout=sleep_seconds
                )
                # If we get here, shutdown was signaled
                break
            except asyncio.TimeoutError:
                # Normal timeout - continue to next cycle
                pass

        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
            # Pause before retry to avoid tight error loop
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=10)
                break
            except asyncio.TimeoutError:
                pass

    logger.info("Background worker stopped")


async def start_background_worker():
    """Start worker if ENABLE_BACKGROUND_WORKER=true."""
    global _worker_task, _shutdown_event

    # Check environment variable
    enabled = os.getenv("ENABLE_BACKGROUND_WORKER", "").lower() in (
        "true",
        "1",
        "yes",
    )

    if not enabled:
        logger.info("Background worker disabled (ENABLE_BACKGROUND_WORKER not set)")
        return

    if _worker_task is not None:
        logger.warning("Background worker already running")
        return

    _shutdown_event = asyncio.Event()
    _worker_task = asyncio.create_task(background_worker_loop(_shutdown_event))


async def stop_background_worker():
    """Gracefully stop worker."""
    global _worker_task, _shutdown_event

    if _worker_task is None:
        return

    logger.info("Stopping background worker...")
    _shutdown_event.set()

    try:
        await asyncio.wait_for(_worker_task, timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning("Worker did not stop gracefully, cancelling...")
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass

    _worker_task = None
    _shutdown_event = None
