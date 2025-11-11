"""
Tests for AiFilterFeed (smart filter) functionality.

These tests verify that:
1. AiFilterFeed correctly filters posts based on AI responses
"""

from datetime import timedelta
from unittest.mock import Mock

from rss_glue.feeds.ai_client import AiClient, AiClientResponse
from rss_glue.feeds.rss import RssFeed
from rss_glue.feeds.smart_filter import AiFilterFeed

from .test_utils import mock_rss_feed


class TestSmartFilter:
    """Test suite for the AiFilterFeed class."""

    def test_smart_filter_basic_filtering(self, fs_config, mock_http_requests):
        """Test that smart filter correctly filters posts based on AI responses."""
        mock_rss_feed()

        # Create a source feed
        source_feed = RssFeed(
            id="test_feed",
            url="https://example.com/feed.xml",
            limit=10,
            interval=timedelta(hours=1),
        )
        fs_config([source_feed])
        source_feed.update()

        # Create a mock AI client
        mock_client = Mock(spec=AiClient)

        # Configure the mock to return different responses for different posts
        # We'll say "yes" to the first post and "no" to the others
        responses = [
            AiClientResponse(response="yes", tokens_used=100),
            AiClientResponse(response="no", tokens_used=100),
            AiClientResponse(response="no", tokens_used=100),
        ]
        mock_client.get_response.side_effect = responses

        # Create the smart filter
        filter_feed = AiFilterFeed(
            source=source_feed,
            client=mock_client,
            prompt="Only include posts about technology",
            limit=10,
        )
        fs_config([source_feed, filter_feed])

        # Update the filter (this will call the AI client)
        filter_feed.update()

        # Get filtered posts
        filtered_posts = filter_feed.posts()

        # Should only have 1 post (the one that got "yes")
        assert len(filtered_posts) == 1

        # Verify the AI client was called 3 times (once for each source post)
        assert mock_client.get_response.call_count == 3

        # Verify the filtered post has the expected attributes
        filtered_post = filtered_posts[0]
        assert filtered_post.include_post is True
        assert filtered_post.token_cost == 100
        assert filtered_post.namespace == f"smart_filter_{source_feed.namespace}"

    def test_smart_filter_updates_when_source_updated_but_not_due(
        self, fs_config, mock_http_requests
    ):
        """Test that smart filter needs update when source was updated more recently, even if source doesn't need update."""
        mock_rss_feed()

        # Create a source feed
        source_feed = RssFeed(
            id="test_feed",
            url="https://example.com/feed.xml",
            limit=10,
            interval=timedelta(hours=1),
        )
        fs_config([source_feed])
        source_feed.update()

        # Create a mock AI client
        mock_client = Mock(spec=AiClient)
        mock_client.get_response.return_value = AiClientResponse(response="yes", tokens_used=100)

        # Create the smart filter but don't update it yet
        filter_feed = AiFilterFeed(
            source=source_feed,
            client=mock_client,
            prompt="Only include posts about technology",
            limit=10,
        )
        fs_config([source_feed, filter_feed])

        # At this point, source has been updated but filter hasn't
        # So source.last_updated > filter.last_updated (or filter.last_updated is None)
        assert source_feed.last_updated is not None

        # Check next_update - should return True even though source doesn't need update
        next_update_time, needs_update = filter_feed.next_update(force=False)

        # Should indicate it needs an update because source was updated more recently
        assert needs_update is True
        assert next_update_time == source_feed.last_updated
