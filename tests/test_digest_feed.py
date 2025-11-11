"""
Tests for DigestFeed functionality.

These tests verify that:
1. DigestFeed correctly creates digest posts from a merge of Instagram feeds
2. Posts are filtered by the digest time window
3. Posts are sorted by score and limited correctly
4. Digest issues are created for the correct time periods
"""

from datetime import datetime, timedelta, timezone

from croniter import croniter

from rss_glue.cli import _update
from rss_glue.feeds.digest import DigestFeed
from rss_glue.feeds.instagram import InstagramFeed
from rss_glue.feeds.merge import MergeFeed

from .test_utils import create_instagram_post, register_instagram_api_mock


class TestDigestFeed:
    """Test suite for the DigestFeed class."""

    def test_digest_of_merge_instagram_feeds(self, fs_config, mock_http_requests, freezer):
        """
        Test that DigestFeed correctly creates a digest from a merge of two Instagram feeds.

        This test:
        1. Creates two Instagram feeds with posts at specific times
        2. Merges them into a single feed
        3. Creates a digest feed with a daily schedule
        4. Verifies the digest contains posts from both feeds within the time window
        5. Verifies posts are sorted by score (likes) and limited correctly
        6. Verifies posts outside the time window are excluded
        """
        # Freeze time to a known point: 2024-01-15 12:00:00 UTC
        now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        freezer.move_to(now)

        # Set up a daily digest schedule (midnight UTC)
        schedule = "0 0 * * *"  # Daily at midnight

        # Calculate the last digest period using croniter
        # The last period would be from 2024-01-14 00:00 to 2024-01-15 00:00
        itr = croniter(schedule, now)
        period_end = itr.get_prev(datetime)  # 2024-01-15 00:00
        period_start = itr.get_prev(datetime)  # 2024-01-14 00:00

        # Create posts with timestamps within the digest window
        post1_time = period_start + timedelta(hours=2)  # 2024-01-14 02:00
        post2_time = period_start + timedelta(hours=6)  # 2024-01-14 06:00
        post3_time = period_start + timedelta(hours=10)  # 2024-01-14 10:00
        post4_time = period_start + timedelta(hours=14)  # 2024-01-14 14:00

        # Create posts for first Instagram feed (user_a)
        user_a_posts = [
            create_instagram_post(
                post_id="user_a_1",
                username="user_a",
                caption_text="Check out this cool photo!",
                taken_at_timestamp=post1_time.timestamp(),
                like_count=150,  # Higher score
                comment_count=20,
            ),
            create_instagram_post(
                post_id="user_a_2",
                username="user_a",
                caption_text="New items just arrived!",
                taken_at_timestamp=post2_time.timestamp(),
                like_count=80,  # Lower score
                comment_count=5,
            ),
        ]

        # Create posts for second Instagram feed (user_b)
        user_b_posts = [
            create_instagram_post(
                post_id="user_b_1",
                username="user_b",
                caption_text="Group event this weekend!",
                taken_at_timestamp=post3_time.timestamp(),
                like_count=200,  # Highest score
                comment_count=30,
            ),
            create_instagram_post(
                post_id="user_b_2",
                username="user_b",
                caption_text="Morning gathering",
                taken_at_timestamp=post4_time.timestamp(),
                like_count=120,  # Medium score
                comment_count=15,
            ),
        ]

        # Mock the Instagram API responses
        register_instagram_api_mock(user_a_posts, "user_a")
        register_instagram_api_mock(user_b_posts, "user_b")

        # Create two Instagram feeds
        user_a_feed = InstagramFeed(
            username="user_a",
            api_key="test_api_key",
            interval=timedelta(hours=6),
        )

        user_b_feed = InstagramFeed(
            username="user_b",
            api_key="test_api_key",
            interval=timedelta(hours=6),
        )

        # Create a merge feed from the two Instagram feeds
        merge_feed = MergeFeed(
            "instagram_merge",
            user_a_feed,
            user_b_feed,
            title="Instagram Merge",
        )

        # Create a digest feed from the merge feed
        digest_feed = DigestFeed(
            source=merge_feed,
            limit=10,
            schedule=schedule,
            back_issues=1,  # Only create digest for the most recent period
        )

        # Configure and update using CLI
        fs_config([digest_feed])
        _update()

        # Get the digest posts
        digest_posts = digest_feed.posts()

        # Verify we have exactly one digest post
        assert len(digest_posts) == 1, f"Expected 1 digest post, got {len(digest_posts)}"

        digest_post = digest_posts[0]

        # Verify the digest post properties
        assert digest_post.namespace == "digest_merge_instagram_merge"
        assert digest_post.posted_time == period_end
        assert digest_post.author == "RSS Glue"

        # Verify the digest contains posts from both feeds
        subposts = digest_post.subposts
        assert len(subposts) == 4, f"Expected 4 subposts, got {len(subposts)}"

        # Verify posts are sorted by score (likes) in descending order
        scores = [post.score() for post in subposts]
        assert scores == sorted(scores, reverse=True), "Subposts should be sorted by score"

        # Verify the highest scoring post is first
        assert subposts[0].id == "user_b_1"  # 200 likes
        assert subposts[1].id == "user_a_1"  # 150 likes
        assert subposts[2].id == "user_b_2"  # 120 likes
        assert subposts[3].id == "user_a_2"  # 80 likes

        # Verify posts are from both source feeds
        user_a_subposts = [p for p in subposts if "user_a" in p.id]
        user_b_subposts = [p for p in subposts if "user_b" in p.id]
        assert len(user_a_subposts) == 2
        assert len(user_b_subposts) == 2

        # Verify the digest post can be rendered
        html = digest_post.render()
        assert html
        assert isinstance(html, str)
        assert "Check out this cool photo!" in html
        assert "Group event this weekend!" in html

    def test_digest_respects_limit_and_excludes_outside_window(
        self, fs_config, mock_http_requests, freezer
    ):
        """
        Test that DigestFeed respects the limit parameter and excludes posts outside the time window.
        Combined test to reduce duplication.
        """
        # Freeze time
        now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        freezer.move_to(now)

        # Set up a daily digest schedule
        schedule = "0 0 * * *"

        # Calculate the digest period
        itr = croniter(schedule, now)
        period_end = itr.get_prev(datetime)
        period_start = itr.get_prev(datetime)

        # Create posts: some inside window with different scores, some outside
        posts = [
            # Post BEFORE the window (should be excluded)
            create_instagram_post(
                post_id="too_old",
                username="test_user",
                caption_text="Too old",
                taken_at_timestamp=(period_start - timedelta(hours=1)).timestamp(),
                like_count=1000,  # High score but outside window
            ),
            # Posts INSIDE the window (should be included)
            create_instagram_post(
                post_id="post_0",
                username="test_user",
                caption_text="Post 0",
                taken_at_timestamp=(period_start + timedelta(hours=2)).timestamp(),
                like_count=100,  # Highest score in window
            ),
            create_instagram_post(
                post_id="post_1",
                username="test_user",
                caption_text="Post 1",
                taken_at_timestamp=(period_start + timedelta(hours=4)).timestamp(),
                like_count=90,
            ),
            create_instagram_post(
                post_id="post_2",
                username="test_user",
                caption_text="Post 2",
                taken_at_timestamp=(period_start + timedelta(hours=6)).timestamp(),
                like_count=80,
            ),
            create_instagram_post(
                post_id="post_3",
                username="test_user",
                caption_text="Post 3",
                taken_at_timestamp=(period_start + timedelta(hours=8)).timestamp(),
                like_count=70,  # Will be excluded due to limit
            ),
            # Post AFTER the window (should be excluded)
            create_instagram_post(
                post_id="too_new",
                username="test_user",
                caption_text="Too new",
                taken_at_timestamp=(period_end + timedelta(hours=1)).timestamp(),
                like_count=2000,  # High score but outside window
            ),
        ]

        # Mock the Instagram API
        register_instagram_api_mock(posts, "test_user")

        # Create Instagram feed
        instagram_feed = InstagramFeed(
            username="test_user",
            api_key="test_api_key",
            interval=timedelta(hours=6),
        )

        # Create digest with a limit of 3
        digest_feed = DigestFeed(
            source=instagram_feed,
            limit=3,  # Only include top 3 posts
            schedule=schedule,
            back_issues=1,
        )

        fs_config([digest_feed])
        _update()

        # Get the digest posts
        digest_posts = digest_feed.posts()
        assert len(digest_posts) == 1

        # Verify only 3 subposts are included (the top scoring ones within the window)
        digest_post = digest_posts[0]
        assert len(digest_post.subposts) == 3

        # Verify they are the highest scoring posts within the window
        post_ids = [p.id for p in digest_post.subposts]
        assert digest_post.subposts[0].id == "post_0"  # 100 likes
        assert digest_post.subposts[1].id == "post_1"  # 90 likes
        assert digest_post.subposts[2].id == "post_2"  # 80 likes

        # Verify posts outside the window are excluded
        assert "too_old" not in post_ids
        assert "too_new" not in post_ids
        # Verify the 4th post is excluded due to limit
        assert "post_3" not in post_ids
