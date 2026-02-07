"""Tests for the Instagram feed handler."""

import hashlib
from datetime import datetime, timezone

from rss_glue.feeds.instagram import SCRAPE_API_BASE, InstagramFeedHandler
from rss_glue.models.db import SystemConfig

from tests.fixtures.instagram import INSTAGRAM_API_RESPONSE


FEED_ID = "test-instagram"
FEED_CONFIG = {"username": "testuser", "limit": 50}


def _setup_api_key(session):
    """Insert the required API key into the test database."""
    session.add(SystemConfig(key="scrape_creators_key", value="fake-key-for-testing"))
    session.commit()


class TestInstagramFetch:
    def test_returns_all_posts(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        assert len(posts) == 3

    def test_external_id_is_deterministic_hash(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        raw_id = "3001234567890123456"
        expected = hashlib.sha256(raw_id.encode()).hexdigest()[:16]
        assert posts[0]["external_id"] == expected

    def test_published_at_is_utc(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        for post in posts:
            assert post["published_at"].tzinfo is not None
            assert post["published_at"].tzinfo == timezone.utc

    def test_timestamps_parsed_correctly(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        assert posts[0]["published_at"] == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)

    def test_link_from_shortcode(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        assert posts[0]["link"] == "https://www.instagram.com/p/CxABCDEfgh1/"

    def test_title_is_first_line_of_caption(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        assert posts[0]["title"] == "Golden hour at the beach"

    def test_missing_caption_uses_fallback_title(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        # Post 3 has caption: None
        assert posts[2]["title"] == "Instagram Post"

    def test_author_format(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        assert posts[0]["author"] == "@testuser"

    def test_score_equals_like_count(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        assert posts[0]["score"] == 4200.0
        assert posts[1]["score"] == 1500.0
        assert posts[2]["score"] == 890.0

    def test_single_image_in_content(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        # Post 1 is a single image
        assert "image1_full.jpg" in posts[0]["content"]

    def test_carousel_images_in_content(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        # Post 2 is a carousel with 3 images
        content = posts[1]["content"]
        assert "carousel_1.jpg" in content
        assert "carousel_2.jpg" in content
        assert "carousel_3.jpg" in content

    def test_video_has_watch_link_and_poster(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        # Post 3 is a video
        content = posts[2]["content"]
        assert "Watch Video" in content
        assert "video1_poster.jpg" in content

    def test_music_info_in_content(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        # Post 1 has music metadata
        assert "Summer Breeze" in posts[0]["content"]
        assert "DJ Chill" in posts[0]["content"]

    def test_engagement_metrics_in_content(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        assert "4,200" in posts[0]["content"]
        assert "87" in posts[0]["content"]

    def test_missing_api_key_returns_empty(self, db_session, mock_api):
        # Don't add API key
        posts = InstagramFeedHandler.fetch(FEED_ID, FEED_CONFIG, db_session)

        assert posts == []

    def test_limit_respected(self, db_session, mock_api):
        _setup_api_key(db_session)
        mock_api.get(SCRAPE_API_BASE).respond(json=INSTAGRAM_API_RESPONSE)

        config = {"username": "testuser", "limit": 1}
        posts = InstagramFeedHandler.fetch(FEED_ID, config, db_session)

        assert len(posts) == 1
