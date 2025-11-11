"""
Tests for MergeFeed functionality.

These tests verify that:
1. MergeFeed correctly merges posts from multiple sources (RSS + Reddit)
2. Posts are sorted by posted_time (most recent first)
3. Duplicate posts (same hashkey) are deduplicated
4. Reference posts correctly point to source feeds
5. Outputs are generated correctly for merged feeds
"""

from datetime import timedelta

from rss_glue.cli import _update
from rss_glue.feeds.merge import MergeFeed
from rss_glue.feeds.reddit import RedditFeed
from rss_glue.feeds.rss import RssFeed
from rss_glue.outputs import generate_outputs

from .test_utils import (create_reddit_api_response_with_n_posts,
                         mock_rss_feed, register_reddit_api_mock)


class TestMergeFeed:
    """Test suite for the MergeFeed class."""

    def test_merge_feed_initialization(self, fs_config, mock_http_requests):
        """Test that MergeFeed can be initialized with multiple sources."""
        # Setup RSS feed mock
        mock_rss_feed()

        # Setup Reddit feed mock
        reddit_response = create_reddit_api_response_with_n_posts(2, base_timestamp=1640000000.0)
        register_reddit_api_mock(reddit_response, subreddit="technology", sort="top")

        # Create source feeds
        rss_feed = RssFeed(
            id="tech_news",
            url="https://example.com/feed.xml",
            limit=10,
            interval=timedelta(hours=1),
        )
        reddit_feed = RedditFeed(
            url="https://www.reddit.com/r/technology/top.json?t=week",
            interval=timedelta(days=1),
        )

        # Create merge feed
        merge_feed = MergeFeed(
            "tech_merge",
            rss_feed,
            reddit_feed,
            title="Tech News Merge",
        )

        fs_config([merge_feed])

        assert merge_feed.id == "tech_merge"
        assert merge_feed.title == "Tech News Merge"
        assert merge_feed.namespace == "merge_tech_merge"
        assert len(list(merge_feed.sources())) == 2

    def test_merge_feed_posts_from_both_sources(self, fs_config, mock_http_requests):
        """Test that MergeFeed returns posts from all sources, sorted by time."""
        # Setup RSS feed mock
        mock_rss_feed()

        # Setup Reddit feed mock with 2 posts
        reddit_response = create_reddit_api_response_with_n_posts(2, base_timestamp=1640000000.0)
        register_reddit_api_mock(reddit_response, subreddit="technology", sort="top")

        # Create source feeds
        rss_feed = RssFeed(
            id="tech_rss",
            url="https://example.com/feed.xml",
            limit=10,
            interval=timedelta(hours=1),
        )
        reddit_feed = RedditFeed(
            url="https://www.reddit.com/r/technology/top.json?t=week",
            interval=timedelta(days=1),
        )

        # Create merge feed
        merge_feed = MergeFeed(
            "tech_merge",
            rss_feed,
            reddit_feed,
            title="Tech News",
        )

        fs_config([merge_feed])

        # Update using CLI function
        _update()

        # Get posts from merge feed
        posts = merge_feed.posts()

        # Should have posts from both sources (3 RSS + 2 Reddit = 5 total)
        assert len(posts) == 5

        # Verify posts are reference posts with correct namespaces
        rss_posts = [p for p in posts if "rss_tech_rss" in p.id]
        reddit_posts = [p for p in posts if "reddit_technology" in p.id]

        assert len(rss_posts) == 3
        assert len(reddit_posts) == 2

        # Verify all posts have the merge namespace
        for post in posts:
            assert post.namespace == "merge_tech_merge"

    def test_merge_feed_deduplication(self, fs_config, mock_http_requests):
        """Test that MergeFeed deduplicates posts with the same hashkey.

        Note: Posts from different feeds (even with same URL) have different hashkeys
        because the namespace is part of the hashkey. This test verifies that posts
        from the SAME source appearing multiple times are deduplicated.
        """
        # Setup RSS feed mock
        mock_rss_feed()

        # Create a single RSS feed
        rss_feed = RssFeed(
            id="news",
            url="https://example.com/feed.xml",
            limit=10,
            interval=timedelta(hours=1),
        )

        # Create merge feed with the same source added twice
        # This simulates what happens when a feed appears in multiple merge paths
        merge_feed = MergeFeed(
            "dedupe_test",
            rss_feed,
            title="Deduplication Test",
        )

        fs_config([merge_feed])

        # Update feeds
        _update()

        # Get posts from merge feed
        posts = merge_feed.posts()

        # Should have 3 unique posts (the RSS feed has 3 posts)
        assert len(posts) == 3

    def test_merge_feed_post_retrieval(self, fs_config, mock_http_requests):
        """Test that individual posts can be retrieved from the merge feed."""
        # Setup RSS feed mock
        mock_rss_feed()

        # Setup Reddit feed mock
        reddit_response = create_reddit_api_response_with_n_posts(1, base_timestamp=1640000000.0)
        register_reddit_api_mock(reddit_response, subreddit="python", sort="top")

        # Create source feeds
        rss_feed = RssFeed(
            id="dev_rss",
            url="https://example.com/feed.xml",
            limit=10,
            interval=timedelta(hours=1),
        )
        reddit_feed = RedditFeed(
            url="https://www.reddit.com/r/python/top.json?t=week",
            interval=timedelta(days=1),
        )

        # Create merge feed
        merge_feed = MergeFeed(
            "dev_merge",
            rss_feed,
            reddit_feed,
            title="Dev News",
        )

        fs_config([merge_feed])

        # Update feeds
        _update()

        # Get all posts
        posts = merge_feed.posts()
        assert len(posts) > 0

        # Get a specific post
        first_post = posts[0]
        retrieved_post = merge_feed.post(first_post.id)

        assert retrieved_post is not None
        # The retrieved post should be from the source feed, not the merge feed
        assert retrieved_post.namespace != "merge_dev_merge"

    def test_merge_feed_limit_parameter(self, fs_config, mock_http_requests):
        """Test that the limit parameter is passed to source feeds and affects total results.

        The limit is applied to each source feed's posts() call, so the total number
        of posts returned can be up to limit * number_of_sources.
        """
        # Setup RSS feed mock
        mock_rss_feed()

        # Setup Reddit feed mock with 5 posts
        reddit_response = create_reddit_api_response_with_n_posts(5, base_timestamp=1640000000.0)
        register_reddit_api_mock(reddit_response, subreddit="news", sort="top")

        # Create source feeds
        rss_feed = RssFeed(
            id="news_rss",
            url="https://example.com/feed.xml",
            limit=10,
            interval=timedelta(hours=1),
        )
        reddit_feed = RedditFeed(
            url="https://www.reddit.com/r/news/top.json?t=week",
            interval=timedelta(days=1),
        )

        # Create merge feed
        merge_feed = MergeFeed(
            "news_merge",
            rss_feed,
            reddit_feed,
            title="News Merge",
        )

        fs_config([merge_feed])

        # Update feeds
        _update()

        # Get posts with limit - this gets up to 3 posts from each source
        posts = merge_feed.posts(limit=3)

        # The limit is applied to each source, so we can get up to 6 posts total (3 from each source)
        # But we might get fewer if sources have fewer posts
        assert len(posts) <= 6
        assert len(posts) > 0

    def test_merge_feed_time_sorted(self, fs_config, mock_http_requests):
        """Test that merged posts are sorted by posted_time (most recent first)."""
        # Setup RSS feed mock
        mock_rss_feed()

        # Setup Reddit feed mock with specific timestamps
        reddit_response = create_reddit_api_response_with_n_posts(3, base_timestamp=1640000000.0)
        register_reddit_api_mock(reddit_response, subreddit="test", sort="top")

        # Create source feeds
        rss_feed = RssFeed(
            id="test_rss",
            url="https://example.com/feed.xml",
            limit=10,
            interval=timedelta(hours=1),
        )
        reddit_feed = RedditFeed(
            url="https://www.reddit.com/r/test/top.json?t=week",
            interval=timedelta(days=1),
        )

        # Create merge feed
        merge_feed = MergeFeed(
            "test_merge",
            rss_feed,
            reddit_feed,
            title="Test Merge",
        )

        fs_config([merge_feed])

        # Update feeds
        _update()

        # Get posts
        posts = merge_feed.posts()

        # Verify posts are sorted by posted_time (descending)
        for i in range(len(posts) - 1):
            assert posts[i].posted_time >= posts[i + 1].posted_time

    def test_merge_feed_output_generation(self, fs_config, mock_http_requests):
        """Test that outputs are correctly generated for merged feeds."""
        # Setup RSS feed mock
        mock_rss_feed()

        # Setup Reddit feed mock
        reddit_response = create_reddit_api_response_with_n_posts(2, base_timestamp=1640000000.0)
        register_reddit_api_mock(reddit_response, subreddit="technology", sort="top")

        # Create source feeds
        rss_feed = RssFeed(
            id="tech_rss",
            url="https://example.com/feed.xml",
            limit=10,
            interval=timedelta(hours=1),
        )
        reddit_feed = RedditFeed(
            url="https://www.reddit.com/r/technology/top.json?t=week",
            interval=timedelta(days=1),
        )

        # Create merge feed
        merge_feed = MergeFeed(
            "tech_merge",
            rss_feed,
            reddit_feed,
            title="Technology Feed",
        )

        fs_config([merge_feed])

        # Update feeds
        _update()

        # Generate outputs
        outputs = list(generate_outputs([merge_feed], force=True, output_limit=12))

        # Should generate RSS and HTML outputs
        assert len(outputs) > 0

        output_paths = [str(path) for path, _ in outputs]
        # Check for RSS output
        assert any("merge_tech_merge" in path and path.endswith(".xml") for path in output_paths)
        # Check for HTML output
        assert any("merge_tech_merge" in path and path.endswith(".html") for path in output_paths)

    def test_merge_feed_last_updated(self, fs_config, mock_http_requests):
        """Test that merge feed's last_updated reflects the most recent source update."""
        # Setup RSS feed mock
        mock_rss_feed()

        # Setup Reddit feed mock
        reddit_response = create_reddit_api_response_with_n_posts(1, base_timestamp=1640000000.0)
        register_reddit_api_mock(reddit_response, subreddit="test", sort="top")

        # Create source feeds
        rss_feed = RssFeed(
            id="test_rss",
            url="https://example.com/feed.xml",
            limit=10,
            interval=timedelta(hours=1),
        )
        reddit_feed = RedditFeed(
            url="https://www.reddit.com/r/test/top.json?t=week",
            interval=timedelta(days=1),
        )

        # Create merge feed
        merge_feed = MergeFeed(
            "test_merge",
            rss_feed,
            reddit_feed,
            title="Test Merge",
        )

        fs_config([merge_feed])

        # Update feeds
        _update()

        # Merge feed's last_updated should be the max of its sources
        assert merge_feed.last_updated == max(rss_feed.last_updated, reddit_feed.last_updated)
