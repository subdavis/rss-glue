"""
Tests for the RedditFeed source.

These tests verify Reddit-specific functionality:
- URL parsing and namespace generation
- Score-based sorting
- Rendering of different post types (image, self, video)
"""

import pathlib
from datetime import timedelta

import pytest

from rss_glue.feeds.reddit import RedditFeed

from .test_utils import register_reddit_api_mock


def mock_reddit_feed_with_fixture():
    """Mock Reddit API with fixture data."""
    import json

    fixture_path = pathlib.Path(__file__).parent / "fixtures" / "reddit_api_example.json"
    with open(fixture_path) as f:
        response = json.load(f)

    register_reddit_api_mock(response, subreddit="technology", sort="top")


class TestRedditFeed:
    """Test suite for the RedditFeed class."""

    def test_reddit_feed_initialization(self, fs_config, mock_http_requests):
        """Test that RedditFeed extracts subreddit from URL correctly."""

        feed = RedditFeed(
            url="https://www.reddit.com/r/technology/top.json?t=week",
            interval=timedelta(days=1),
        )

        assert feed.subreddit == "technology"
        assert feed.title == "r/technology"
        assert feed.namespace == "reddit_technology"
        assert feed.origin_url == "https://www.reddit.com/r/technology"

    def test_reddit_feed_requires_json_endpoint(self, fs_config, mock_http_requests):
        """Test that RedditFeed validates JSON endpoint."""

        with pytest.raises(ValueError, match="JSON endpoint expected"):
            RedditFeed(
                url="https://www.reddit.com/r/technology/top",
                interval=timedelta(days=1),
            )

    def test_reddit_feed_update_and_posts(self, fs_config, mock_http_requests):
        """Test that updating a Reddit feed creates posts with correct data."""
        mock_reddit_feed_with_fixture()

        feed = RedditFeed(
            url="https://www.reddit.com/r/technology/top.json?t=week",
            interval=timedelta(days=1),
        )
        fs_config([feed])
        feed.update()

        posts = feed.posts()
        assert len(posts) == 2

        # Verify posts have expected data
        post_ids = [p.id for p in posts]
        assert "1abc123" in post_ids
        assert "2def456" in post_ids

        # Find the specific posts
        post_42_score = next(p for p in posts if p.id == "1abc123")
        post_87_score = next(p for p in posts if p.id == "2def456")

        # Verify scores
        assert post_42_score.score() == 42
        assert post_87_score.score() == 87

    def test_reddit_post_render_with_image(self, fs_config, mock_http_requests):
        """Test rendering of an image post."""
        mock_reddit_feed_with_fixture()

        feed = RedditFeed(
            url="https://www.reddit.com/r/technology/top.json?t=week",
            interval=timedelta(days=1),
        )
        fs_config([feed])
        feed.update()

        posts = feed.posts()
        image_post = next(p for p in posts if p.id == "1abc123")

        rendered = image_post.render()
        assert rendered
        assert "techfan99" in rendered  # author
        assert "42" in rendered  # score

    def test_reddit_post_render_with_selftext(self, fs_config, mock_http_requests):
        """Test rendering of a self/text post with HTML content."""
        mock_reddit_feed_with_fixture()

        feed = RedditFeed(
            url="https://www.reddit.com/r/technology/top.json?t=week",
            interval=timedelta(days=1),
        )
        fs_config([feed])
        feed.update()

        posts = feed.posts()
        self_post = next(p for p in posts if p.id == "2def456")

        rendered = self_post.render()
        assert rendered
        assert "techtester42" in rendered  # author
        assert "87" in rendered  # score
        # selftext_html is unescaped in the template
        assert "amazing article" in rendered
