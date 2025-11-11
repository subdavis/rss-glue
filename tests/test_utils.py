"""
Test utilities for RSS Glue tests.

This module provides common helper functions to reduce duplication in tests,
including:
- Feed API response mocking (RSS, Reddit, Instagram, Facebook, HackerNews)
- Feed registration helpers
- HTTP mocking utilities
"""

import json
import pathlib
from typing import Optional

import httpretty

from rss_glue.feeds import feed
from rss_glue.resources import global_config

# =============================================================================
# Reddit API Mocking
# =============================================================================


def create_reddit_api_response_with_n_posts(n: int, base_timestamp: float) -> dict:
    """
    Create a Reddit API response with n posts.

    Posts are created with timestamps going backwards from base_timestamp,
    and scores that increase with index (so later posts have higher scores).

    Args:
        n: Number of posts to create
        base_timestamp: Unix timestamp for the first post (subsequent posts go backwards in time)

    Returns:
        dict: Reddit API response in the format expected by RedditFeed
    """
    posts = []
    for i in range(n):
        # Create posts with different timestamps (going backwards in time)
        # and different scores (increasing with index)
        post_timestamp = base_timestamp - (i * 3600)  # 1 hour apart
        posts.append(
            {
                "kind": "t3",
                "data": {
                    "id": f"post_{i}",
                    "title": f"Test Post {i}",
                    "author": f"user_{i}",
                    "score": 100 + (i * 10),  # Higher index = higher score
                    "created_utc": post_timestamp,
                    "permalink": f"/r/test/comments/post_{i}/test_post_{i}/",
                    "url": f"https://i.redd.it/test_image_{i}.jpg",
                    "post_hint": "image",
                    "selftext": f"Test content {i}",
                    "selftext_html": f'&lt;div class="md"&gt;&lt;p&gt;Test content {i}&lt;/p&gt;\n&lt;/div&gt;',
                    "url_overridden_by_dest": f"https://i.redd.it/test_image_{i}.jpg",
                    "subreddit": "test",
                },
            }
        )

    return {"kind": "Listing", "data": {"children": posts}}


def register_reddit_api_mock(response_data: dict, subreddit: str = "test", sort: str = "top"):
    """
    Register HTTP mock for Reddit API endpoint.

    Args:
        response_data: Reddit API response dict
        subreddit: Subreddit name (default: "test")
        sort: Sort parameter (default: "top")
    """
    httpretty.register_uri(
        httpretty.GET,
        f"https://www.reddit.com/r/{subreddit}/{sort}.json?t=week",
        body=json.dumps(response_data),
        content_type="application/json",
        status=200,
    )


def mock_rss_feed(
    custom_body: Optional[str] = None, image_urls: Optional[list[tuple[str, bytes]]] = None
):
    """
    Mock an RSS feed response.

    Args:
        custom_body: Optional custom RSS XML body. If not provided, uses sample_rss_feed.xml fixture.
        image_urls: Optional list of (url, image_data) tuples to mock image downloads.
    """
    # Read from real filesystem since fixtures aren't in fake filesystem
    if custom_body is None:
        fixture_path = pathlib.Path(__file__).parent / "fixtures" / "sample_rss_feed.xml"
        body = fixture_path.read_text()
    else:
        body = custom_body

    httpretty.register_uri(
        httpretty.GET,
        "https://example.com/feed.xml",
        body=body,
        content_type="application/rss+xml",
    )

    # Mock any image URLs if provided
    if image_urls:
        for url, image_data in image_urls:
            httpretty.register_uri(
                httpretty.GET,
                url,
                body=image_data,
                content_type="image/jpeg",
                status=200,
            )


def create_instagram_post(
    post_id: str,
    username: str,
    caption_text: str,
    taken_at_timestamp: float,
    like_count: int = 100,
    comment_count: int = 10,
) -> dict:
    """
    Create an Instagram post dict in the format expected by InstagramFeed.

    Args:
        post_id: Unique ID for the post
        username: Instagram username
        caption_text: Caption text for the post
        taken_at_timestamp: Unix timestamp when the post was created
        like_count: Number of likes (affects score)
        comment_count: Number of comments

    Returns:
        dict: Instagram post data
    """
    return {
        "id": post_id,
        "pk": post_id,
        "code": f"CODE_{post_id}",
        "taken_at": taken_at_timestamp,
        "media_type": 1,  # Image
        "like_count": like_count,
        "comment_count": comment_count,
        "user": {"username": username},
        "caption": {"text": caption_text},
        "image_versions2": {
            "candidates": [
                {
                    "url": f"https://example.com/image_{post_id}.jpg",
                    "width": 1080,
                    "height": 1080,
                }
            ]
        },
    }


def register_instagram_api_mock(posts: list[dict], username: str):
    """
    Register HTTP mock for Instagram API endpoint.

    Args:
        posts: List of Instagram post dicts (created with create_instagram_post)
        username: Instagram username to mock
    """
    response = {"items": posts, "status": "ok"}
    httpretty.register_uri(
        httpretty.GET,
        f"https://api.scrapecreators.com/v2/instagram/user/posts?handle={username}",
        body=json.dumps(response),
        content_type="application/json",
        status=200,
    )


def mock_instagram_api():
    """Mock Instagram API response for test_user with a single post."""
    # Create a single post using the create_instagram_post helper
    # Data based on the fixture but simplified
    post = create_instagram_post(
        post_id="3733845226143174017_218077178",
        username="test_user",
        caption_text="Sample post content for testing purposes",
        taken_at_timestamp=1759329058,  # From fixture: October 01, 2025
        like_count=123,
        comment_count=5,
    )

    register_instagram_api_mock([post], "test_user")


def mock_facebook_api():
    """Mock Facebook API response."""
    fixture_path = pathlib.Path(__file__).parent / "fixtures" / "facebook_api_example.json"
    with open(fixture_path) as f:
        response = json.load(f)

    httpretty.register_uri(
        httpretty.GET,
        "https://api.scrapecreators.com/v1/facebook/group/posts",
        body=json.dumps(response),
        content_type="application/json",
        status=200,
    )


def mock_hackernews_api():
    """Mock HackerNews API responses."""
    fixtures_dir = pathlib.Path(__file__).parent / "fixtures"

    with open(fixtures_dir / "hackernews_stories.json") as f:
        stories = json.load(f)

    with open(fixtures_dir / "hackernews_story_1.json") as f:
        story_1 = json.load(f)

    with open(fixtures_dir / "hackernews_story_2.json") as f:
        story_2 = json.load(f)

    with open(fixtures_dir / "hackernews_comment.json") as f:
        comment = json.load(f)

    with open(fixtures_dir / "hackernews_comment_2.json") as f:
        comment_2 = json.load(f)

    # Register the mock for top stories list
    httpretty.register_uri(
        httpretty.GET,
        "https://hacker-news.firebaseio.com/v0/topstories.json",
        body=json.dumps(stories),
        content_type="application/json",
        status=200,
    )

    # Register mocks for individual stories
    httpretty.register_uri(
        httpretty.GET,
        "https://hacker-news.firebaseio.com/v0/item/38734567.json",
        body=json.dumps(story_1),
        content_type="application/json",
        status=200,
    )

    httpretty.register_uri(
        httpretty.GET,
        "https://hacker-news.firebaseio.com/v0/item/38734568.json",
        body=json.dumps(story_2),
        content_type="application/json",
        status=200,
    )

    # Register mock for comments
    httpretty.register_uri(
        httpretty.GET,
        "https://hacker-news.firebaseio.com/v0/item/38734600.json",
        body=json.dumps(comment),
        content_type="application/json",
        status=200,
    )

    httpretty.register_uri(
        httpretty.GET,
        "https://hacker-news.firebaseio.com/v0/item/38734700.json",
        body=json.dumps(comment_2),
        content_type="application/json",
        status=200,
    )
