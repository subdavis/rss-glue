import html
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests

from rss_glue.feeds import feed
from rss_glue.resources import global_config, short_hash_string


@dataclass
class CachedFeedItem(feed.ReferenceFeedItem):
    """
    A CachedFeedItem extends AliasFeed to add image and video caching functionality.
    It inherits the subpost wrapping behavior and adds image/video URL replacement.
    """

    def render(self) -> str:
        """
        Render the subpost content, but replace remote image and video URLs with local cached versions.
        """
        # print(self.subpost)
        content = self.subpost.render()

        # Find all img tags with src attributes
        img_pattern = re.compile(r'<img\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)

        # Find all video tags with src attributes
        video_pattern = re.compile(r'<video\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)

        # Find all source tags within video elements
        source_pattern = re.compile(r'<source\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)

        def replace_media(match, media_type="image"):
            original_tag = match.group(0)
            media_url = match.group(1)

            # Skip data URLs and already local URLs
            if media_url.startswith("data:") or media_url.startswith(global_config.base_url):
                return original_tag

            # Try to cache the media
            try:
                cached_path = self._cache_media(media_url, media_type)
                if cached_path:
                    # Replace the src attribute with the local path
                    # Construct the relative URL from the base URL
                    # RSS clients will not handle relative paths correctly, they need full urls.
                    relative_url = urljoin(global_config.base_url, str(cached_path))
                    new_tag = original_tag.replace(media_url, relative_url)
                    self.logger.debug(f"Cached {media_type}: {media_url} -> {relative_url}")
                    return new_tag
            except Exception as e:
                self.logger.warning(f"Failed to cache {media_type} {media_url}: {e}")

            return original_tag

        # Replace all image URLs
        cached_content = img_pattern.sub(lambda m: replace_media(m, "image"), content)
        # Replace all video URLs
        cached_content = video_pattern.sub(lambda m: replace_media(m, "video"), cached_content)
        # Replace all source URLs (within video tags)
        cached_content = source_pattern.sub(lambda m: replace_media(m, "video"), cached_content)

        return cached_content

    def _cache_media(self, url: str, media_type: str = "image") -> Optional[Path]:
        """
        Download and cache a media file (image or video), returning the relative path to the cached file.

        :param url: The URL of the media to cache
        :param media_type: Type of media ("image" or "video")
        :return: The relative path to the cached file, or None if caching failed
        """
        # Generate a unique key for this media based on its URL
        media_key = short_hash_string(url)
        unescaped_url = html.unescape(url)  # URL may be HTML-escaped

        # Determine extension and media type folder
        if media_type == "video":
            ext = "mp4"
            media_folder = "videos"
        else:
            ext = "jpg"
            media_folder = "images"

        # Create filename with hash and extension
        filename = f"{media_key}.{ext}"

        # Check if already cached or previously failed
        cache_path = global_config.media_cache.getPath(filename, media_folder)

        # Check if successfully cached (fast path - no need to check .failed)
        if cache_path.exists():
            return global_config.media_cache.getRelativePath(filename, media_folder)

        # Only check for failed downloads if the cache file doesn't exist
        if self._is_failed_download(cache_path):
            self.logger.debug(f"Skipping previously failed {media_type} download: {unescaped_url}")
            return None

        # Download the media
        try:
            response = requests.get(
                unescaped_url,
                timeout=30,  # Longer timeout for videos
                headers={"User-Agent": "Mozilla/5.0 (compatible; RSS-Glue/1.0)"},
                stream=True,  # Stream for potentially large video files
            )
            global_config.sleep()
            response.raise_for_status()

            # Write the binary data
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            self.logger.info(
                f"Downloaded and cached {media_type} for post {self.id}: {unescaped_url}"
            )
            return global_config.media_cache.getRelativePath(filename, media_folder)
        except Exception as e:
            self.logger.error(f"Failed to download {media_type} {unescaped_url}: {e}")
            # Mark this download as failed so we don't retry it
            self._mark_failed_download(cache_path, str(e))
            return None

    def _is_failed_download(self, path: Path) -> bool:
        """
        Check if a download previously failed by looking for a .failed metadata file.

        :param path: Path to check (the normal cache file path, not the .failed path)
        :return: True if a .failed marker exists for this path
        """
        failed_marker = path.with_suffix(path.suffix + ".failed")
        return failed_marker.exists()

    def _mark_failed_download(self, path: Path, error_message: str) -> None:
        """
        Mark a download as failed by creating a .failed metadata file.
        The .failed file contains metadata about the failure (timestamp and error message).

        :param path: Path where the file would have been cached
        :param error_message: Error message to store in the metadata file
        """
        try:
            # Ensure parent directory exists
            path.parent.mkdir(parents=True, exist_ok=True)

            # Create .failed metadata file (no empty file needed)
            failed_marker = path.with_suffix(path.suffix + ".failed")
            metadata = {
                "timestamp": time.time(),
                "error": error_message,
                "url_hash": path.stem,  # Store the hash for reference
            }

            with open(failed_marker, "w") as f:
                json.dump(metadata, f, indent=2)

            self.logger.debug(f"Marked failed download: {failed_marker}")
        except Exception as e:
            self.logger.error(f"Failed to mark failed download at {path}: {e}")


class CacheFeed(feed.AliasFeed):
    """
    A CacheFeed wraps another feed and caches images and videos from post content.
    """

    name = "cache"
    post_cls: type[CachedFeedItem] = CachedFeedItem
