"""
Tests for feed locking behavior with HTTP error responses.

These tests verify that feeds automatically lock when encountering
4xx or 5xx HTTP errors to prevent repeated failed update attempts.
"""

import json
from datetime import timedelta

import httpretty

from rss_glue.cli import _update
from rss_glue.feeds.reddit import RedditFeed


class TestFeedLockingOn4xxErrors:
    """Test suite for automatic feed locking on 4xx client errors."""

    def test_reddit_feed_locks_on_404_not_found(self, fs_config, mock_http_requests):
        """Test that a Reddit feed locks itself when receiving a 404 error."""
        # Register a 404 response
        httpretty.register_uri(
            httpretty.GET,
            "https://www.reddit.com/r/nonexistent/top.json?t=week",
            status=404,
            body="Not Found",
        )

        feed = RedditFeed(
            url="https://www.reddit.com/r/nonexistent/top.json?t=week",
            interval=timedelta(days=1),
        )
        fs_config([feed])

        # Feed should not be locked initially
        assert not feed.locked

        _update()

        assert feed.locked


class TestManualLockingAndUnlocking:
    """Test manual lock/unlock operations."""

    def test_manual_unlock_allows_updates(self, fs_config, mock_http_requests):
        """Test that manually unlocking a feed allows updates."""
        reddit_response = {
            "kind": "Listing",
            "data": {"children": []},
        }
        httpretty.register_uri(
            httpretty.GET,
            "https://www.reddit.com/r/technology/top.json?t=week",
            body=json.dumps(reddit_response),
            content_type="application/json",
            status=200,
        )

        feed = RedditFeed(
            url="https://www.reddit.com/r/technology/top.json?t=week",
            interval=timedelta(days=1),
        )
        fs_config([feed])

        # Lock then unlock
        feed.lock()
        assert feed.locked

        # Force should override the lock
        next_time, needs_update = feed.next_update(force=True)
        assert needs_update

        feed.unlock()
        assert not feed.locked

        # Should now be able to check for updates
        next_time, needs_update = feed.next_update(force=False)
        # First run should need update
        assert needs_update
