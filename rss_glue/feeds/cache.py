"""
CacheFeed - A composable feed wrapper that caches images from post content.

This module provides a CacheFeed class that wraps another feed and automatically
downloads and caches images referenced in post HTML content. This helps avoid:
- CORS issues when displaying images from external sources
- Broken links from expired or unstable image URLs

Usage example:
    from rss_glue.feeds import RssFeed, CacheFeed

    # Create a source feed
    source = RssFeed("example", "https://example.com/feed.xml")

    # Wrap it with CacheFeed to cache images
    cached = CacheFeed(source)

    # Use cached feed in your artifacts
    artifacts = [HtmlOutput(cached)]

The CacheFeed stores images in the file cache under an "images/" namespace
and rewrites <img> tags to point to the locally cached versions.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import requests

from rss_glue.feeds import feed
from rss_glue.resources import global_config, short_hash_string


@dataclass
class CachedFeedItem(feed.ReferenceFeedItem):
    """
    A CachedFeedItem extends ReferenceFeedItem to add image caching functionality.
    It inherits the subpost wrapping behavior and adds image URL replacement.
    """

    def render(self) -> str:
        """
        Render the subpost content, but replace remote image URLs with local cached versions.
        """
        content = self.subpost.render()

        # Find all img tags with src attributes
        img_pattern = re.compile(r'<img\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)

        def replace_image(match):
            original_tag = match.group(0)
            image_url = match.group(1)

            # Skip data URLs and already local URLs
            if image_url.startswith("data:") or image_url.startswith("/"):
                return original_tag

            # Try to cache the image
            try:
                cached_path = self._cache_image(image_url)
                if cached_path:
                    # Replace the src attribute with the local path
                    # Construct the relative URL from the static root
                    relative_url = urljoin(global_config.base_url, str(cached_path))
                    new_tag = original_tag.replace(image_url, relative_url)
                    self.logger.debug(f"Cached image: {image_url} -> {relative_url}")
                    return new_tag
            except Exception as e:
                self.logger.warning(f"Failed to cache image {image_url}: {e}")

            return original_tag

        # Replace all image URLs
        cached_content = img_pattern.sub(replace_image, content)
        return cached_content

    def _cache_image(self, url: str) -> Optional[Path]:
        """
        Download and cache an image, returning the relative path to the cached file.

        :param url: The URL of the image to cache
        :return: The relative path to the cached file, or None if caching failed
        """
        # Generate a unique key for this image based on its URL
        image_key = short_hash_string(url)

        # Determine file extension from URL
        parsed_url = urlparse(url)
        path = parsed_url.path
        ext = Path(path).suffix.lstrip(".") or "jpg"

        # Only cache common image formats
        valid_extensions = ["jpg", "jpeg", "png", "gif", "webp", "svg"]
        if ext.lower() not in valid_extensions:
            ext = "jpg"

        # Check if already cached
        cache_path = global_config.file_cache.getPath(image_key, ext, f"images/{self.namespace}")
        if cache_path.exists():
            return global_config.file_cache.getRelativePath(
                image_key, ext, f"images/{self.namespace}"
            )

        # Download the image
        try:
            response = requests.get(
                url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (compatible; RSS-Glue/1.0)"}
            )
            response.raise_for_status()

            # Write the binary data
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "wb") as f:
                f.write(response.content)

            return global_config.file_cache.getRelativePath(
                image_key, ext, f"images/{self.namespace}"
            )
        except Exception as e:
            self.logger.error(f"Failed to download image {url}: {e}")
            return None

    @staticmethod
    def load(obj: dict, source: "CacheFeed"):
        """
        Override ReferenceFeedItem.load() to get the subpost from source.source
        instead of directly from source.
        """
        obj["subpost"] = source.source.post(obj["subpost"])
        if not obj["subpost"]:
            source.logger.error(f"missing reference ns={obj['namespace']} subpost={obj['id']}")
        return obj


class CacheFeed(feed.ReferenceFeed):
    """
    A CacheFeed wraps another feed and caches images from post content.
    """

    name = "cache"
    post_cls: type[CachedFeedItem] = CachedFeedItem
