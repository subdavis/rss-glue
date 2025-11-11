"""
Tests for HTML and RSS generator caching behavior.

These tests verify that:
1. HTML generator respects cached files and doesn't regenerate unnecessarily
2. RSS generator respects cached files and doesn't regenerate unnecessarily
"""

from datetime import timedelta

from rss_glue.feeds.rss import RssFeed
from rss_glue.outputs.html import generate_html
from rss_glue.outputs.rss import generate_rss
from rss_glue.resources import global_config

from .test_utils import mock_rss_feed


class TestGeneratorCaching:
    """Test suite for HTML and RSS generator caching behavior."""

    def test_html_generator_caching(self, fs_config, mock_http_requests):
        """Test that HTML generator uses cache and doesn't regenerate when not needed."""
        mock_rss_feed()

        feed = RssFeed(id="test_feed", url="https://example.com/feed.xml", limit=10)
        fs_config([feed])
        feed.update()

        # First generation - should create the file
        first_outputs = list(generate_html([feed], force=False, limit=10))
        assert len(first_outputs) == 1
        first_source, first_path, first_modified = first_outputs[0]

        # Get the file path and check it exists
        html_path = global_config.file_cache.getPath(feed.namespace, "html", "html")
        assert html_path.exists()
        first_mtime = html_path.stat().st_mtime

        # Second generation - should use cache (not regenerate)
        second_outputs = list(generate_html([feed], force=False, limit=10))
        assert len(second_outputs) == 1
        second_source, second_path, second_modified = second_outputs[0]

        # Verify the file wasn't regenerated (mtime should be the same)
        second_mtime = html_path.stat().st_mtime
        assert (
            first_mtime == second_mtime
        ), "HTML file was regenerated when it should have been cached"

        # Verify the paths are the same
        assert first_path == second_path

        # Verify sources are the same
        assert first_source.namespace == second_source.namespace

    def test_rss_generator_caching(self, fs_config, mock_http_requests):
        """Test that RSS generator uses cache and doesn't regenerate when not needed."""
        mock_rss_feed()

        feed = RssFeed(id="test_feed", url="https://example.com/feed.xml", limit=10)
        fs_config([feed])
        feed.update()

        # First generation - should create the file
        first_outputs = list(generate_rss([feed], force=False, limit=10))
        assert len(first_outputs) == 1
        first_source, first_path, first_modified = first_outputs[0]

        # Get the file path and check it exists
        rss_path = global_config.file_cache.getPath(feed.namespace, "xml", "rss")
        assert rss_path.exists()
        first_mtime = rss_path.stat().st_mtime

        # Second generation - should use cache (not regenerate)
        second_outputs = list(generate_rss([feed], force=False, limit=10))
        assert len(second_outputs) == 1
        second_source, second_path, second_modified = second_outputs[0]

        # Verify the file wasn't regenerated (mtime should be the same)
        second_mtime = rss_path.stat().st_mtime
        assert (
            first_mtime == second_mtime
        ), "RSS file was regenerated when it should have been cached"

        # Verify the paths are the same
        assert first_path == second_path

        # Verify sources are the same
        assert first_source.namespace == second_source.namespace
