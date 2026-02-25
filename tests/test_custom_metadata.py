"""Tests for custom metadata on PostDict and RSS namespace extension.

Validates that:
- Base handler populates metadata (score, source_feed_id, source_feed_type)
- Merge handler preserves metadata opaquely from source feeds
- Smart filter handler preserves metadata from source feed
- period_start/period_end filtering works
- The feedgen rssglue namespace extension emits correct XML elements
"""

from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree

from sqlmodel import Session, SQLModel, create_engine

import pytest

# Import feed handler modules so they register with FeedRegistry
import rss_glue.feeds.merge  # noqa: F401
import rss_glue.feeds.smart_filter  # noqa: F401
from rss_glue.feeds.registry import BaseFeedHandler, FeedRegistry, PostDict
from rss_glue.feeds.rssglue_ext import (
    RSSGLUE_NS,
    RssGlueEntryExtension,
    RssGlueExtension,
)
from rss_glue.feeds.smart_filter import FilterDecision
from rss_glue.models.db import (
    Feed,
    FeedRelationship,
    FeedTag,
    Post,
    Tag,
)


@pytest.fixture
def db_session():
    """In-memory SQLite session with all tables created."""
    engine = create_engine("sqlite://", echo=False)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_feed(session: Session, feed_id: str, feed_type: str, **kwargs) -> Feed:
    feed = Feed(id=feed_id, type=feed_type, name=feed_id, **kwargs)
    session.add(feed)
    session.commit()
    session.refresh(feed)
    return feed


def _make_post(
    session: Session,
    feed_id: str,
    external_id: str,
    title: str = "Test Post",
    published_at: datetime | None = None,
    score: int | None = None,
) -> Post:
    if published_at is None:
        published_at = datetime.now(timezone.utc)
    post = Post(
        feed_id=feed_id,
        external_id=external_id,
        title=title,
        content=f"Content of {title}",
        link=f"https://example.com/{external_id}",
        author="tester",
        score=score,
        published_at=published_at,
    )
    session.add(post)
    session.commit()
    session.refresh(post)
    return post


# ---------------------------------------------------------------------------
# Base handler metadata
# ---------------------------------------------------------------------------


class TestBaseHandlerMetadata:
    def test_get_posts_includes_metadata(self, db_session):
        _make_feed(db_session, "rss-1", "rss")
        _make_post(db_session, "rss-1", "post-a", score=42)

        posts = BaseFeedHandler.get_posts("rss-1", 10, db_session)

        assert len(posts) == 1
        meta = posts[0]["metadata"]
        assert meta["score"] == 42
        assert meta["source_feed_id"] == "rss-1"
        assert meta["source_feed_type"] == "rss"

    def test_get_posts_includes_post_id(self, db_session):
        _make_feed(db_session, "rss-1", "rss")
        db_post = _make_post(db_session, "rss-1", "post-a")

        posts = BaseFeedHandler.get_posts("rss-1", 10, db_session)

        assert posts[0]["post_id"] == db_post.id

    def test_metadata_score_none_when_no_score(self, db_session):
        _make_feed(db_session, "rss-1", "rss")
        _make_post(db_session, "rss-1", "post-a", score=None)

        posts = BaseFeedHandler.get_posts("rss-1", 10, db_session)
        assert posts[0]["metadata"]["score"] is None


# ---------------------------------------------------------------------------
# Period filtering
# ---------------------------------------------------------------------------


class TestPeriodFiltering:
    def test_period_start_filters_old_posts(self, db_session):
        _make_feed(db_session, "rss-1", "rss")
        now = datetime.now(timezone.utc)
        _make_post(db_session, "rss-1", "old", published_at=now - timedelta(days=10))
        _make_post(db_session, "rss-1", "new", published_at=now - timedelta(hours=1))

        posts = BaseFeedHandler.get_posts(
            "rss-1", 10, db_session, period_start=now - timedelta(days=1)
        )

        assert len(posts) == 1
        assert posts[0]["id"] == "new"

    def test_period_end_filters_future_posts(self, db_session):
        _make_feed(db_session, "rss-1", "rss")
        now = datetime.now(timezone.utc)
        _make_post(db_session, "rss-1", "old", published_at=now - timedelta(days=2))
        _make_post(db_session, "rss-1", "new", published_at=now - timedelta(hours=1))

        posts = BaseFeedHandler.get_posts(
            "rss-1", 10, db_session, period_end=now - timedelta(days=1)
        )

        assert len(posts) == 1
        assert posts[0]["id"] == "old"

    def test_period_range(self, db_session):
        _make_feed(db_session, "rss-1", "rss")
        now = datetime.now(timezone.utc)
        _make_post(db_session, "rss-1", "p1", published_at=now - timedelta(days=5))
        _make_post(db_session, "rss-1", "p2", published_at=now - timedelta(days=3))
        _make_post(db_session, "rss-1", "p3", published_at=now - timedelta(days=1))

        posts = BaseFeedHandler.get_posts(
            "rss-1",
            10,
            db_session,
            period_start=now - timedelta(days=4),
            period_end=now - timedelta(days=2),
        )

        assert len(posts) == 1
        assert posts[0]["id"] == "p2"


# ---------------------------------------------------------------------------
# Limit=0 means no limit
# ---------------------------------------------------------------------------


class TestLimitZero:
    def test_limit_zero_returns_all(self, db_session):
        _make_feed(db_session, "rss-1", "rss")
        for i in range(5):
            _make_post(db_session, "rss-1", f"post-{i}")

        posts = BaseFeedHandler.get_posts("rss-1", 0, db_session)
        assert len(posts) == 5

    def test_limit_positive_caps_results(self, db_session):
        _make_feed(db_session, "rss-1", "rss")
        for i in range(5):
            _make_post(db_session, "rss-1", f"post-{i}")

        posts = BaseFeedHandler.get_posts("rss-1", 2, db_session)
        assert len(posts) == 2


# ---------------------------------------------------------------------------
# Merge handler preserves metadata
# ---------------------------------------------------------------------------


class TestMergeMetadataPreservation:
    def _setup_merge(self, session: Session):
        """Create two source feeds with a merge feed combining them via tags."""
        _make_feed(session, "src-a", "rss")
        _make_feed(session, "src-b", "rss")

        tag = Tag(name="all")
        session.add(tag)
        session.commit()
        session.refresh(tag)

        session.add(FeedTag(feed_id="src-a", tag_id=tag.id))
        session.add(FeedTag(feed_id="src-b", tag_id=tag.id))
        session.commit()

        merge_feed = _make_feed(session, "merged", "merge", config={"include_tags": ["all"]})

        now = datetime.now(timezone.utc)
        _make_post(session, "src-a", "a1", title="From A", score=10, published_at=now - timedelta(hours=2))
        _make_post(session, "src-b", "b1", title="From B", score=20, published_at=now - timedelta(hours=1))

        return merge_feed

    def test_merge_includes_metadata_from_sources(self, db_session):
        self._setup_merge(db_session)
        handler = FeedRegistry.get_handler("merge")

        posts = handler.get_posts("merged", 10, db_session)

        assert len(posts) == 2
        # Posts should be sorted newest first
        assert posts[0]["metadata"]["source_feed_id"] == "src-b"
        assert posts[0]["metadata"]["score"] == 20
        assert posts[1]["metadata"]["source_feed_id"] == "src-a"
        assert posts[1]["metadata"]["score"] == 10

    def test_merge_preserves_source_feed_type(self, db_session):
        self._setup_merge(db_session)
        handler = FeedRegistry.get_handler("merge")

        posts = handler.get_posts("merged", 10, db_session)

        for post in posts:
            assert post["metadata"]["source_feed_type"] == "rss"

    def test_merge_passes_period_filters_to_sources(self, db_session):
        self._setup_merge(db_session)
        handler = FeedRegistry.get_handler("merge")

        now = datetime.now(timezone.utc)
        # Only get posts from the last 90 minutes (excludes src-a's post)
        posts = handler.get_posts(
            "merged", 10, db_session,
            period_start=now - timedelta(minutes=90),
        )

        assert len(posts) == 1
        assert posts[0]["metadata"]["source_feed_id"] == "src-b"


# ---------------------------------------------------------------------------
# Smart filter preserves metadata
# ---------------------------------------------------------------------------


class TestSmartFilterMetadataPreservation:
    def _setup_smart_filter(self, session: Session):
        """Create a source feed + smart_filter feed with one approved post."""
        _make_feed(session, "src", "rss")
        _make_feed(session, "filtered", "smart_filter", config={"prompt": "test", "model": "test"})

        # Link smart_filter -> source via FeedRelationship
        session.add(FeedRelationship(parent_feed_id="filtered", child_feed_id="src"))
        session.commit()

        now = datetime.now(timezone.utc)
        post_a = _make_post(session, "src", "a1", title="Approved", score=99, published_at=now - timedelta(hours=1))
        post_b = _make_post(session, "src", "b1", title="Rejected", score=5, published_at=now)

        # Pre-create filter decisions
        session.add(FilterDecision(feed_id="filtered", post_external_id="a1", approved=True, reason="yes"))
        session.add(FilterDecision(feed_id="filtered", post_external_id="b1", approved=False, reason="no"))
        session.commit()

    def test_smart_filter_preserves_metadata(self, db_session):
        self._setup_smart_filter(db_session)
        handler = FeedRegistry.get_handler("smart_filter")

        posts = handler.get_posts("filtered", 10, db_session)

        assert len(posts) == 1
        assert posts[0]["title"] == "Approved"
        meta = posts[0]["metadata"]
        assert meta["score"] == 99
        assert meta["source_feed_id"] == "src"
        assert meta["source_feed_type"] == "rss"

    def test_smart_filter_passes_period_to_source(self, db_session):
        self._setup_smart_filter(db_session)
        handler = FeedRegistry.get_handler("smart_filter")

        # Use a period that excludes the approved post
        far_future = datetime.now(timezone.utc) + timedelta(days=10)
        posts = handler.get_posts(
            "filtered", 10, db_session,
            period_start=far_future,
        )

        assert len(posts) == 0


# ---------------------------------------------------------------------------
# feedgen RSS namespace extension
# ---------------------------------------------------------------------------


class TestRssGlueExtension:
    def test_extension_registers_namespace(self):
        from feedgen.feed import FeedGenerator

        fg = FeedGenerator()
        fg.register_extension(
            "rssglue",
            extension_class_feed=RssGlueExtension,
            extension_class_entry=RssGlueEntryExtension,
            rss=True,
            atom=False,
        )
        fg.title("Test")
        fg.link(href="http://example.com")
        fg.description("Test feed")

        rss_xml = fg.rss_str(pretty=True).decode("utf-8")
        assert RSSGLUE_NS in rss_xml

    def test_entry_metadata_appears_in_rss(self):
        from feedgen.feed import FeedGenerator

        fg = FeedGenerator()
        fg.register_extension(
            "rssglue",
            extension_class_feed=RssGlueExtension,
            extension_class_entry=RssGlueEntryExtension,
            rss=True,
            atom=False,
        )
        fg.title("Test")
        fg.link(href="http://example.com")
        fg.description("Test feed")

        entry = fg.add_entry()
        entry.title("Post 1")
        entry.link(href="http://example.com/1")
        entry.rssglue.metadata({
            "score": 42,
            "source_feed_id": "hn",
            "source_feed_type": "hackernews",
        })

        rss_xml = fg.rss_str(pretty=True).decode("utf-8")

        # Parse and check the elements exist
        root = ElementTree.fromstring(rss_xml)
        item = root.find(".//item")
        assert item is not None

        ns = {"rssglue": RSSGLUE_NS}
        assert item.findtext("rssglue:score", namespaces=ns) == "42"
        assert item.findtext("rssglue:source_feed_id", namespaces=ns) == "hn"
        assert item.findtext("rssglue:source_feed_type", namespaces=ns) == "hackernews"

    def test_none_values_are_omitted(self):
        from feedgen.feed import FeedGenerator

        fg = FeedGenerator()
        fg.register_extension(
            "rssglue",
            extension_class_feed=RssGlueExtension,
            extension_class_entry=RssGlueEntryExtension,
            rss=True,
            atom=False,
        )
        fg.title("Test")
        fg.link(href="http://example.com")
        fg.description("Test feed")

        entry = fg.add_entry()
        entry.title("Post 1")
        entry.link(href="http://example.com/1")
        entry.rssglue.metadata({
            "score": None,
            "source_feed_id": "rss-1",
            "source_feed_type": "rss",
        })

        rss_xml = fg.rss_str(pretty=True).decode("utf-8")
        root = ElementTree.fromstring(rss_xml)
        item = root.find(".//item")
        ns = {"rssglue": RSSGLUE_NS}

        # score is None so should not appear
        assert item.find("rssglue:score", namespaces=ns) is None
        # but source_feed_id should
        assert item.findtext("rssglue:source_feed_id", namespaces=ns) == "rss-1"

    def test_empty_metadata_adds_nothing(self):
        from feedgen.feed import FeedGenerator

        fg = FeedGenerator()
        fg.register_extension(
            "rssglue",
            extension_class_feed=RssGlueExtension,
            extension_class_entry=RssGlueEntryExtension,
            rss=True,
            atom=False,
        )
        fg.title("Test")
        fg.link(href="http://example.com")
        fg.description("Test feed")

        entry = fg.add_entry()
        entry.title("Post 1")
        entry.link(href="http://example.com/1")
        # Don't call metadata() at all

        rss_xml = fg.rss_str(pretty=True).decode("utf-8")
        root = ElementTree.fromstring(rss_xml)
        item = root.find(".//item")
        ns = {"rssglue": RSSGLUE_NS}

        assert item.find("rssglue:score", namespaces=ns) is None
        assert item.find("rssglue:source_feed_id", namespaces=ns) is None
