"""
Tests for RssFeed functionality.

These tests verify that:
1. RssFeed correctly fetches and parses RSS feeds
2. Posts are properly cached and retrieved
3. RSS and HTML outputs are generated correctly
"""

from datetime import timedelta

from rss_glue.feeds.rss import RssFeed
from rss_glue.outputs import generate_outputs
from rss_glue.resources import global_config

from .test_utils import mock_rss_feed


class TestRssFeed:
    """Test suite for the RssFeed class."""

    def test_rss_feed_initialization(self, fs_config, mock_http_requests):
        """Test that RssFeed can be initialized with basic parameters."""
        mock_rss_feed()

        feed = RssFeed(
            id="test_feed",
            url="https://example.com/feed.xml",
            limit=10,
            interval=timedelta(hours=1),
        )
        fs_config([feed])

        assert feed.id == "test_feed"
        assert feed.url == "https://example.com/feed.xml"
        assert feed.limit == 10
        assert feed.namespace == "rss_test_feed"

        # Get all posts
        feed.update()
        posts = feed.posts()
        assert len(posts) == 3

        # Check first post
        first_post = posts[0]
        assert "First Post Title" in first_post.title or "Second Post Title" in first_post.title
        assert first_post.namespace == "rss_test_feed"
        assert first_post.origin_url.startswith("https://example.com/posts/")

    def test_rss_feed_with_enclosure(self, fs_config, mock_http_requests):
        """Test that posts with enclosures are correctly parsed."""
        mock_rss_feed()

        feed = RssFeed(id="test_feed", url="https://example.com/feed.xml", limit=10)
        fs_config([feed])
        feed.update()

        posts = feed.posts()

        posts_with_enclosures = [p for p in posts if p.enclosure is not None]
        assert len(posts_with_enclosures) == 1

        post_with_enclosure = posts_with_enclosures[0]
        assert post_with_enclosure.enclosure.url == "https://example.com/images/post2.jpg"
        assert post_with_enclosure.enclosure.type == "image/jpeg"
        assert post_with_enclosure.enclosure.length == 12345

    def test_rss_feed_limit(self, fs_config, mock_http_requests):
        """Test that the limit parameter correctly restricts the number of posts."""
        mock_rss_feed()

        feed = RssFeed(id="test_feed", url="https://example.com/feed.xml", limit=2)
        fs_config([feed])
        feed.update()

        posts = feed.posts()
        assert len(posts) == 2

    def test_rss_feed_caching_behavior(self, fs_config, mock_http_requests):
        """Test that subsequent updates don't re-fetch already cached posts."""
        mock_rss_feed()

        feed = RssFeed(id="test_feed", url="https://example.com/feed.xml", limit=10)
        fs_config([feed])
        # First update
        feed.update()
        last_updated_first = feed.last_updated

        # Second update (should use cache)
        feed.update()
        assert feed.last_updated == last_updated_first

    def test_rss_feed_enclosure_rendering(self, fs_config, mock_http_requests):
        """Test that enclosures are correctly rendered in both HTML and RSS outputs."""
        mock_rss_feed()

        feed = RssFeed(id="test_feed", url="https://example.com/feed.xml", limit=10)
        fs_config([feed])
        feed.update()

        # Generate both HTML and RSS outputs
        outputs = list(generate_outputs([feed], force=True, output_limit=10))
        assert len(outputs) >= 2  # At least HTML and RSS outputs

        # Read the generated HTML output
        html_path = global_config.file_cache.getPath(feed.namespace, "html", "html")
        assert html_path.exists()
        html_content = html_path.read_text()

        # Verify enclosure is rendered in HTML as an image tag
        assert "https://example.com/images/post2.jpg" in html_content
        assert '<img src="https://example.com/images/post2.jpg"' in html_content

        # Read the generated RSS output (in Atom format)
        rss_path = global_config.file_cache.getPath(feed.namespace, "xml", "rss")
        assert rss_path.exists()
        rss_content = rss_path.read_text()

        # Verify enclosure is included in the Atom feed
        # In Atom format, enclosures are represented as link elements
        assert "https://example.com/images/post2.jpg" in rss_content
        # The enclosure should be in the entry for "Second Post Title"
        assert "<title>Second Post Title</title>" in rss_content
        # Verify the link element with the enclosure URL is present
        assert '<link href="https://example.com/images/post2.jpg"' in rss_content
