"""
Tests for the HackerNewsFeed source.

These tests verify HackerNews-specific functionality:
- Feed type validation (top, new, best)
- Story fetching from Firebase API
- Top comment extraction
- Handling Ask HN posts (no URL)
"""

from datetime import timedelta

import pytest

from rss_glue.feeds.hackernews import HackerNewsFeed

from .test_utils import mock_hackernews_api


class TestHackerNewsFeed:
    """Test suite for the HackerNewsFeed class."""

    def test_hackernews_feed_initialization_top(self, fs_config, mock_http_requests):
        """Test that HackerNewsFeed initializes correctly for 'top' stories."""

        feed = HackerNewsFeed(feed_type="top", interval=timedelta(hours=1))

        assert feed.feed_type == "top"
        assert feed.title == "Hacker News - Top"
        assert feed.namespace == "hackernews_top"
        assert feed.url == "https://hacker-news.firebaseio.com/v0/topstories.json"
        assert feed.origin_url == "https://news.ycombinator.com"

    def test_hackernews_feed_initialization_best(self, fs_config, mock_http_requests):
        """Test that HackerNewsFeed initializes correctly for 'best' stories."""

        feed = HackerNewsFeed(feed_type="best", interval=timedelta(hours=1))

        assert feed.feed_type == "best"
        assert feed.title == "Hacker News - Best"
        assert feed.namespace == "hackernews_best"

    def test_hackernews_feed_invalid_type(self, fs_config, mock_http_requests):
        """Test that HackerNewsFeed rejects invalid feed types."""

        with pytest.raises(ValueError, match="Invalid feed type"):
            HackerNewsFeed(feed_type="invalid")

    def test_hackernews_feed_update_and_stories(self, fs_config, mock_http_requests):
        """Test that updating a HackerNews feed creates stories with correct scores."""
        mock_hackernews_api()

        feed = HackerNewsFeed(feed_type="top", interval=timedelta(hours=1))
        fs_config([feed])
        feed.update()

        posts = feed.posts()
        # We have 2 valid stories in the fixture
        assert len(posts) == 2

        # Verify story IDs
        post_ids = [p.id for p in posts]
        assert "38734567" in post_ids
        assert "38734568" in post_ids

        # Verify scores
        story_1 = next(p for p in posts if p.id == "38734567")
        story_2 = next(p for p in posts if p.id == "38734568")

        assert story_1.score() == 342
        assert story_2.score() == 156

    def test_hackernews_story_with_url(self, fs_config, mock_http_requests):
        """Test rendering of a story with an external URL."""
        mock_hackernews_api()

        feed = HackerNewsFeed(feed_type="top", interval=timedelta(hours=1))
        fs_config([feed])
        feed.update()

        posts = feed.posts()
        story_with_url = next(p for p in posts if p.id == "38734567")

        rendered = story_with_url.render()
        assert rendered
        assert "https://example.com/article" in rendered  # external URL
        assert "pg" in rendered  # author
        assert "342" in rendered  # score
        assert "142" in rendered  # descendants (comment count)
        assert "news.ycombinator.com/item?id=38734567" in rendered  # comments URL

    def test_hackernews_ask_hn_post(self, fs_config, mock_http_requests):
        """Test rendering of Ask HN post (no external URL)."""
        mock_hackernews_api()

        feed = HackerNewsFeed(feed_type="top", interval=timedelta(hours=1))
        fs_config([feed])
        feed.update()

        posts = feed.posts()
        ask_hn_post = next(p for p in posts if p.id == "38734568")

        rendered = ask_hn_post.render()
        assert rendered
        assert "user123" in rendered  # author
        assert "156" in rendered  # score
        # For Ask HN, the URL should point to HN comments
        assert "news.ycombinator.com/item?id=38734568" in rendered

    def test_hackernews_top_comment_included(self, fs_config, mock_http_requests):
        """Test that top comment is fetched and included in story data."""
        mock_hackernews_api()

        feed = HackerNewsFeed(feed_type="top", interval=timedelta(hours=1))
        fs_config([feed])
        feed.update()

        posts = feed.posts()
        story_with_comment = next(p for p in posts if p.id == "38734567")

        # The story_data should include the top_comment
        assert "top_comment" in story_with_comment.story_data
        assert story_with_comment.story_data["top_comment"]["by"] == "commenter1"

        rendered = story_with_comment.render()
        # The comment text should appear in the rendered output
        assert "interesting approach" in rendered
