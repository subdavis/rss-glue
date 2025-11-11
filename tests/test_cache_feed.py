"""
Tests for CacheFeed functionality.

These tests verify that:
1. CacheFeed correctly caches images from feed content
2. Image URLs are replaced with local cached versions
3. Failed downloads are properly marked and skipped
"""

from datetime import timedelta

from rss_glue.feeds.cache import CacheFeed
from rss_glue.feeds.rss import RssFeed
from rss_glue.resources import global_config

from .test_utils import mock_rss_feed


class TestCacheFeed:
    """Test suite for the CacheFeed class."""

    def _create_rss_xml(self, title: str, description: str) -> str:
        """
        Helper method to create RSS XML with a single post.

        Args:
            title: Title of the post
            description: HTML description/content of the post

        Returns:
            RSS XML string
        """
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <description>Test RSS feed with images</description>
    
    <item>
      <title>{title}</title>
      <link>https://example.com/posts/test-post</link>
      <guid>https://example.com/posts/test-post</guid>
      <pubDate>Wed, 13 Nov 2024 10:00:00 GMT</pubDate>
      <description>{description}</description>
    </item>
  </channel>
</rss>"""

    def _create_cache_feed_with_rss(self, rss_body: str, fs_config) -> CacheFeed:
        """
        Helper method to create and configure a CacheFeed with a base RssFeed.

        Args:
            rss_body: The RSS XML body to use
            fs_config: The filesystem configuration fixture

        Returns:
            A configured CacheFeed instance ready for testing
        """
        # Mock the RSS feed
        mock_rss_feed(custom_body=rss_body)

        # Create a base RSS feed
        base_feed = RssFeed(
            id="test_rss",
            url="https://example.com/feed.xml",
            limit=10,
            interval=timedelta(hours=1),
        )

        # Wrap it with CacheFeed
        cache_feed = CacheFeed(source=base_feed)
        fs_config([cache_feed])

        return cache_feed

    def test_cache_feed_replaces_image_urls(self, fs_config, mock_http_requests):
        """Test that CacheFeed downloads images and replaces URLs with local cached versions."""
        # Define test image URL and data
        test_image_url = "https://example.com/test-image.jpg"
        test_image_data = b"\xff\xd8\xff\xe0\x00\x10JFIF"  # Minimal JPEG header

        # Create RSS feed with embedded image in description
        rss_with_image = self._create_rss_xml(
            title="Post with Image",
            description=f'&lt;p&gt;This post has an image:&lt;/p&gt;&lt;img src="{test_image_url}" alt="Test Image"/&gt;',
        )

        # Mock image download
        mock_rss_feed(image_urls=[(test_image_url, test_image_data)])

        # Create and configure cache feed
        cache_feed = self._create_cache_feed_with_rss(rss_with_image, fs_config)

        # Update cache feed - this will fetch the RSS feed and cache images
        cache_feed.update()
        cached_posts = cache_feed.posts()

        assert len(cached_posts) == 1

        # Get the cached post and render it
        cached_post = cached_posts[0]
        rendered_content = cached_post.render()

        # Verify the image URL was replaced with a local cached version
        assert test_image_url not in rendered_content, "Original URL should be replaced"
        assert global_config.base_url in rendered_content, "Should contain base URL"
        assert "images/" in rendered_content, "Should reference images directory"

        # Verify the image was actually downloaded and cached
        images_dir = global_config.static_root / "images"
        assert images_dir.exists(), "Images directory should exist"

        # Images are stored in subdirectories based on hash prefix (first 2 chars)
        # Find all .jpg files recursively
        image_files = list(images_dir.rglob("*.jpg"))
        assert (
            len(image_files) == 1
        ), f"Should have cached exactly one image, found {len(image_files)}"

        # Verify the cached file contains the test image data
        cached_image_path = image_files[0]
        with open(cached_image_path, "rb") as f:
            cached_data = f.read()
        assert cached_data == test_image_data, "Cached image should match original data"

    def test_cache_feed_handles_failed_download(self, fs_config, mock_http_requests):
        """Test that CacheFeed properly handles and marks failed image downloads."""
        # Define test image URLs
        test_image_url = "https://example.com/broken-image.jpg"
        working_image_url = "https://example.com/working-image.jpg"
        working_image_data = b"\xff\xd8\xff\xe0\x00\x10JFIF"  # Minimal JPEG header

        # Create RSS feed with two images - one will fail, one will succeed
        rss_with_images = self._create_rss_xml(
            title="Post with Mixed Images",
            description=f'&lt;p&gt;This post has images:&lt;/p&gt;&lt;img src="{test_image_url}" alt="Broken Image"/&gt;&lt;img src="{working_image_url}" alt="Working Image"/&gt;',
        )

        # Mock working image download
        mock_rss_feed(image_urls=[(working_image_url, working_image_data)])

        # Explicitly mock the broken image to return 404
        import httpretty

        httpretty.register_uri(
            httpretty.GET,
            test_image_url,
            body="Not Found",
            status=404,
        )

        # Create and configure cache feed
        cache_feed = self._create_cache_feed_with_rss(rss_with_images, fs_config)

        # Update cache feed - this will fetch RSS and attempt to cache images
        cache_feed.update()
        cached_posts = cache_feed.posts()

        assert len(cached_posts) == 1

        # Get the cached post and render it
        cached_post = cached_posts[0]
        rendered_content = cached_post.render()

        # Verify the failed image URL was NOT replaced (stays as original)
        assert test_image_url in rendered_content, "Failed image URL should remain unchanged"

        # Verify the working image URL WAS replaced
        assert working_image_url not in rendered_content, "Working image URL should be replaced"
        assert (
            global_config.base_url in rendered_content
        ), "Should contain base URL for cached image"

        # Verify only one image was cached (the working one)
        images_dir = global_config.static_root / "images"
        image_files = list(images_dir.rglob("*.jpg"))
        assert (
            len(image_files) == 1
        ), f"Should have cached exactly one working image, found {len(image_files)}"

        # Verify a .failed marker was created for the broken image
        failed_markers = list(images_dir.rglob("*.jpg.failed"))
        assert len(failed_markers) == 1, "Should have exactly one .failed marker"

        # Verify the .failed marker contains proper metadata
        import json

        failed_marker_path = failed_markers[0]
        with open(failed_marker_path, "r") as f:
            metadata = json.load(f)
        assert "timestamp" in metadata, ".failed marker should have timestamp"
        assert "error" in metadata, ".failed marker should have error message"
        assert "url_hash" in metadata, ".failed marker should have url_hash"

        # Second update should skip the failed download (verify idempotency)
        cache_feed.update()
        cached_posts_2 = cache_feed.posts()
        rendered_content_2 = cached_posts_2[0].render()

        # Should get the same result - failed image still in original URL form
        assert test_image_url in rendered_content_2, "Failed image should still be skipped on retry"
