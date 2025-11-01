import html
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests

from rss_glue.feeds import feed
from rss_glue.resources import global_config, short_hash_string


@dataclass
class CachedFeedItem(feed.ReferenceFeedItem):
    """
    A CachedFeedItem extends AliasFeed to add image caching functionality.
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
            if image_url.startswith("data:") or image_url.startswith(global_config.base_url):
                return original_tag

            # Try to cache the image
            try:
                cached_path = self._cache_image(image_url)
                if cached_path:
                    # Replace the src attribute with the local path
                    # Construct the relative URL from the base URL
                    # RSS clients will not handle relative paths correctly, they need full urls.
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
        unescaped_url = html.unescape(url)  # URL may be HTML-escaped
        ext = "jpg"  # All images get the jpg extension. Often, the URL includes the wrong extension anyway.

        # Check if already cached
        cache_path = global_config.file_cache.getPath(image_key, ext, f"images/{self.namespace}")
        if cache_path.exists():
            return global_config.file_cache.getRelativePath(
                image_key, ext, f"images/{self.namespace}"
            )

        # Download the image
        try:
            response = requests.get(
                unescaped_url,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (compatible; RSS-Glue/1.0)"},
            )
            time.sleep(2)  # Be polite and avoid hammering servers
            response.raise_for_status()

            # Recompute cache_path using the determined extension
            cache_path = global_config.file_cache.getPath(
                image_key, ext, f"images/{self.namespace}"
            )

            # Write the binary data
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "wb") as f:
                f.write(response.content)
            self.logger.info(f"Downloaded and cached image for post {self.id}: {unescaped_url}")
            return global_config.file_cache.getRelativePath(
                image_key, ext, f"images/{self.namespace}"
            )
        except Exception as e:
            self.logger.error(f"Failed to download image {unescaped_url}: {e}")
            return None


class CacheFeed(feed.AliasFeed):
    """
    A CacheFeed wraps another feed and caches images from post content.
    """

    name = "cache"
    post_cls: type[CachedFeedItem] = CachedFeedItem
