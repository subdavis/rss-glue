"""Media caching service for downloading and storing embedded media."""
import hashlib
import mimetypes
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from sqlmodel import Session, select

from rss_glue.models.db import MediaCache, Post

# Media directory relative to the project root
MEDIA_DIR = Path("media")

# Patterns to extract media URLs from HTML content
IMG_PATTERN = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
VIDEO_PATTERN = re.compile(r'<video[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
VIDEO_SOURCE_PATTERN = re.compile(
    r'<source[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE
)
AUDIO_PATTERN = re.compile(r'<audio[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
AUDIO_SOURCE_PATTERN = re.compile(
    r'<source[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE
)

# Common media extensions for guessing content type
MEDIA_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".ogg": "video/ogg",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}


def ensure_media_dir() -> Path:
    """Ensure the media directory exists and return its path."""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_DIR


def url_to_hash(url: str) -> str:
    """Generate a hash from a URL for use as filename."""
    return hashlib.sha256(url.encode()).hexdigest()


def get_extension_from_url(url: str) -> str:
    """Extract file extension from URL, defaulting to empty string."""
    parsed = urlparse(url)
    path = parsed.path
    ext = os.path.splitext(path)[1].lower()
    if ext in MEDIA_EXTENSIONS:
        return ext
    return ""


def get_extension_from_content_type(content_type: Optional[str]) -> str:
    """Get file extension from content type."""
    if not content_type:
        return ""
    # Remove parameters like charset
    content_type = content_type.split(";")[0].strip()
    ext = mimetypes.guess_extension(content_type)
    return ext or ""


def get_local_path(url: str, content_type: Optional[str] = None) -> str:
    """Generate local path for a media URL.

    Format: media/{hash_prefix}/{hash}.{ext}
    Hash prefix is first 2 characters for directory distribution.
    """
    url_hash = url_to_hash(url)
    hash_prefix = url_hash[:2]

    # Try to get extension from content type first, then URL
    ext = get_extension_from_content_type(content_type)
    if not ext:
        ext = get_extension_from_url(url)

    if ext:
        filename = f"{url_hash}{ext}"
    else:
        filename = url_hash

    return f"{hash_prefix}/{filename}"


def extract_media_urls(html_content: str, base_url: Optional[str] = None) -> set[str]:
    """Extract all media URLs from HTML content.

    Args:
        html_content: HTML string to parse
        base_url: Optional base URL for resolving relative URLs

    Returns:
        Set of absolute media URLs
    """
    if not html_content:
        return set()

    urls = set()

    # Extract from img tags
    for match in IMG_PATTERN.finditer(html_content):
        urls.add(match.group(1))

    # Extract from video tags
    for match in VIDEO_PATTERN.finditer(html_content):
        urls.add(match.group(1))

    # Extract from video source tags
    for match in VIDEO_SOURCE_PATTERN.finditer(html_content):
        urls.add(match.group(1))

    # Extract from audio tags
    for match in AUDIO_PATTERN.finditer(html_content):
        urls.add(match.group(1))

    # Extract from audio source tags
    for match in AUDIO_SOURCE_PATTERN.finditer(html_content):
        urls.add(match.group(1))

    # Resolve relative URLs if base_url provided
    if base_url:
        resolved = set()
        for url in urls:
            if url.startswith(("http://", "https://", "//")):
                if url.startswith("//"):
                    url = "https:" + url
                resolved.add(url)
            else:
                resolved.add(urljoin(base_url, url))
        return resolved

    # Filter to only include absolute URLs
    return {url for url in urls if url.startswith(("http://", "https://"))}


def download_media(url: str, timeout: float = 30.0) -> tuple[bytes, Optional[str]]:
    """Download media from a URL.

    Args:
        url: URL to download from
        timeout: Request timeout in seconds

    Returns:
        Tuple of (content bytes, content_type or None)

    Raises:
        httpx.HTTPError: On network errors
    """
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type")
        return response.content, content_type


def cache_media_file(
    url: str,
    feed_id: str,
    post_id: int,
    session: Session,
) -> Optional[MediaCache]:
    """Download and cache a single media file.

    Args:
        url: Media URL to cache
        feed_id: ID of the feed
        post_id: ID of the post
        session: Database session

    Returns:
        MediaCache record if successful, None if failed or already cached
    """
    # Check if already cached
    existing = session.exec(
        select(MediaCache).where(
            MediaCache.original_url == url,
            MediaCache.post_id == post_id,
        )
    ).first()

    if existing:
        return existing

    try:
        # Download the media
        content, content_type = download_media(url)

        # Generate local path
        local_path = get_local_path(url, content_type)
        full_path = MEDIA_DIR / local_path

        # Ensure directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        full_path.write_bytes(content)

        # Create database record
        cache_entry = MediaCache(
            feed_id=feed_id,
            post_id=post_id,
            original_url=url,
            local_path=local_path,
            content_type=content_type,
        )
        session.add(cache_entry)
        session.commit()
        session.refresh(cache_entry)

        return cache_entry

    except Exception:
        # Log error but don't fail the whole process
        return None


def rewrite_content_urls(
    content: str,
    url_mapping: dict[str, str],
    base_url: str,
) -> str:
    """Rewrite media URLs in HTML content to use local cached versions.

    Args:
        content: HTML content to rewrite
        url_mapping: Dict mapping original URLs to local paths
        base_url: Base URL for constructing full URLs to cached media

    Returns:
        HTML content with rewritten URLs
    """
    if not content or not url_mapping:
        return content

    result = content
    for original_url, local_path in url_mapping.items():
        # Construct the full URL to the cached media
        cached_url = f"{base_url.rstrip('/')}/media/{local_path}"
        # Replace both single and double quoted versions
        result = result.replace(f'"{original_url}"', f'"{cached_url}"')
        result = result.replace(f"'{original_url}'", f"'{cached_url}'")

    return result


def process_post_media(
    post: Post,
    session: Session,
    base_url: str,
) -> str:
    """Process and cache all media in a post's content.

    Args:
        post: Post to process
        session: Database session
        base_url: Base URL for rewriting content

    Returns:
        Content with rewritten URLs (or original if no caching done)
    """
    if not post.content:
        return post.content or ""

    # Extract media URLs
    media_urls = extract_media_urls(post.content, post.link)

    if not media_urls:
        return post.content

    # Cache each media file and build URL mapping
    url_mapping = {}
    for url in media_urls:
        cache_entry = cache_media_file(url, post.feed_id, post.id, session)
        if cache_entry:
            url_mapping[url] = cache_entry.local_path

    # Rewrite content with cached URLs
    if url_mapping:
        return rewrite_content_urls(post.content, url_mapping, base_url)

    return post.content
