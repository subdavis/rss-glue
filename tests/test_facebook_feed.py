"""
Tests for the FacebookGroupFeed source.

These tests verify Facebook-specific functionality:
- Group ID extraction from URL
- Reaction count and comment count tracking
- Rendering with multiple images vs single image
"""

from datetime import timedelta

import pytest

from rss_glue.feeds.facebook import FacebookGroupFeed

from .test_utils import mock_facebook_api


class TestFacebookGroupFeed:
    """Test suite for the FacebookGroupFeed class."""

    def test_facebook_post_reactions_and_comments(self, fs_config, mock_http_requests):
        """Test that Facebook posts track reactions and comments correctly."""
        mock_facebook_api()

        feed = FacebookGroupFeed(
            origin_url="https://www.facebook.com/groups/testgroup",
            api_key="test_api_key",
            interval=timedelta(hours=6),
        )
        fs_config([feed])
        assert feed.title == "Facebook Group: testgroup"
        feed.update()

        posts = feed.posts()

        # First post has 42 reactions, 15 comments
        post_1 = next(p for p in posts if p.id == "fb_post_123")
        assert post_1.reactions() == 42
        assert post_1.comments() == 15
        assert post_1.score() == 42.0  # score is based on reactions

        # Second post has 87 reactions, 8 comments
        post_2 = next(p for p in posts if p.id == "fb_post_456")
        assert post_2.reactions() == 87
        assert post_2.comments() == 8
        assert post_2.score() == 87.0

    def test_facebook_post_render_with_multiple_images(self, fs_config, mock_http_requests):
        """Test rendering of a Facebook post with multiple images."""
        mock_facebook_api()

        feed = FacebookGroupFeed(
            origin_url="https://www.facebook.com/groups/testgroup",
            api_key="test_api_key",
            interval=timedelta(hours=6),
        )
        fs_config([feed])
        feed.update()

        posts = feed.posts()
        multi_image_post = next(p for p in posts if p.id == "fb_post_123")

        rendered = multi_image_post.render()
        assert rendered
        assert "John Smith" in rendered  # author name
        assert "42" in rendered  # reactions
        assert "15" in rendered  # comments
        assert "Check out this amazing event" in rendered  # text

    def test_facebook_post_render_with_single_image(self, fs_config, mock_http_requests):
        """Test rendering of a Facebook post with a single image."""
        mock_facebook_api()

        feed = FacebookGroupFeed(
            origin_url="https://www.facebook.com/groups/testgroup",
            api_key="test_api_key",
            interval=timedelta(hours=6),
        )
        fs_config([feed])
        feed.update()

        posts = feed.posts()
        single_image_post = next(p for p in posts if p.id == "fb_post_456")

        rendered = single_image_post.render()
        assert rendered
        assert "Jane Doe" in rendered  # author name
        assert "87" in rendered  # reactions
        assert "Great day today" in rendered  # text
