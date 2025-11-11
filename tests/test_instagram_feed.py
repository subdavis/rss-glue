"""
Tests for the InstagramFeed source.

These tests verify that InstagramFeed correctly fetches, parses, and caches
Instagram post data, using mocked HTTP responses and a fake filesystem.
"""

from datetime import timedelta

from rss_glue.feeds.instagram import InstagramFeed

from .test_utils import mock_instagram_api


class TestInstagramFeed:
    """Test suite for the InstagramFeed class."""

    def test_instagram_feed_update_creates_cache(self, fs_config, mock_http_requests):
        """Test that updating an Instagram feed creates cache files on the filesystem."""
        mock_instagram_api()

        # Create and update the feed
        feed = InstagramFeed(
            username="behindbarsbicycleshop",
            api_key="test_api_key",
            interval=timedelta(hours=6),
        )
        fs_config([feed])
        feed.update()
        assert len(feed.posts()) > 0

    def test_instagram_post_parsing(self, fs_config, mock_http_requests):
        """Test that individual Instagram posts are correctly parsed from the API response."""
        mock_instagram_api()

        feed = InstagramFeed(
            username="behindbarsbicycleshop",
            api_key="test_api_key",
            interval=timedelta(hours=6),
        )
        fs_config([feed])
        feed.update()

        # Get all posts
        posts = feed.posts()
        assert len(posts) >= 1

        # Check first post
        first_post = posts[0]
        assert first_post.namespace == "instagram_behindbarsbicycleshop"
        assert first_post.author
        assert first_post.origin_url.startswith("https://www.instagram.com/p/")
        assert "post_data" in first_post.to_dict()
        assert first_post.likes() >= 0
        assert first_post.comments() >= 0
        assert first_post.score() == float(first_post.likes())

    def test_instagram_post_render(self, fs_config, mock_http_requests):
        """Test that Instagram posts can be rendered to HTML."""
        mock_instagram_api()
        static_root = fs_config

        feed = InstagramFeed(
            username="behindbarsbicycleshop",
            api_key="test_api_key",
        )
        feed.update()

        posts = feed.posts()
        assert len(posts) >= 1

        # Check that post can be rendered
        post = posts[0]
        html = post.render()
        assert html
        assert isinstance(html, str)
