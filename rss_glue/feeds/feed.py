from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from logging import LoggerAdapter
from typing import Iterable, Optional

from rss_glue.logger import logger
from rss_glue.resources import global_config, utc_now
from rss_glue.utils import from_dict, from_subpost


@dataclass
class Enclosure:
    url: str
    type: Optional[str] = None
    length: Optional[int] = None

    def render(self) -> str:
        """
        HTML representation of the enclosure
        """
        if self.type is None:
            return f'<a href="{self.url}">Download Enclosure</a>'
        if self.type.startswith("image/"):
            return f'<img src="{self.url}" style="width: 100%" alt="Enclosure Image"/>'
        elif self.type.startswith("audio/"):
            return f'<audio controls><source src="{self.url}" type="{self.type}">Your browser does not support the audio element.</audio>'
        elif self.type.startswith("video/"):
            return f'<video controls style="width: 100%"><source src="{self.url}" type="{self.type}">Your browser does not support the video element.</video>'
        else:
            return f'<a href="{self.url}">Download Enclosure</a>'


@dataclass
class FeedItem:
    version: int
    namespace: str
    id: str
    author: Optional[str]
    origin_url: str
    title: str
    discovered_time: datetime  # When the post was discovered by us
    posted_time: datetime  # When the post was created according to the source
    enclosure: Optional[Enclosure]

    def __post_init__(self):
        self.logger = NamespaceLogger(logger, {"source": self})
        if type(self.discovered_time) is str:
            self.discovered_time = datetime.fromisoformat(self.discovered_time)
        if type(self.posted_time) is str:
            self.posted_time = datetime.fromisoformat(self.posted_time)
        if type(self.enclosure) is dict:
            self.enclosure = from_dict(Enclosure, self.enclosure)

    def render(self) -> str:
        raise NotImplementedError("FeedItem cannot be rendered")

    def hashkey(self):
        return hash(self.namespace + self.id)

    def score(self) -> float:
        """
        Given a post, return a secondary sort score.
        For social media posts, this could be the number of likes or comments.
        By default, this is the posted_time epoch (chronological order).
        """
        return self.posted_time.timestamp()

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(
            {
                "discovered_time": self.discovered_time.isoformat(),
                "posted_time": self.posted_time.isoformat(),
                "enclosure": asdict(self.enclosure) if self.enclosure else None,
            }
        )
        return d


@dataclass
class ReferenceFeedItem(FeedItem):
    """
    A ReferenceFeedItem contains a reference to another feed item.
    It is only useful if your feed needs to store ADDITIONAL data to the post.
    """

    subpost: FeedItem

    def __post_init__(self):
        if type(self.subpost) is dict:
            subpost_source = global_config.by_namespace(self.subpost.get("namespace"))
            subpost_id = self.subpost.get("id")
            if subpost_source and subpost_id:
                self.subpost = subpost_source.post(subpost_id)
                self.enclosure = self.subpost.enclosure
        return super().__post_init__()

    def render(self):
        return self.subpost.render()

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"subpost": {"namespace": self.subpost.namespace, "id": self.subpost.id}})
        return d

    def hashkey(self):
        return self.subpost.hashkey()

    def score(self) -> float:
        """Delegate score to the subpost"""
        return self.subpost.score()


class NamespaceLogger(LoggerAdapter):

    def process(self, msg, kwargs):
        namespace = getattr(self.extra.get("source"), "namespace", "unknown")
        return f' ns="{namespace}" {msg}', kwargs


class BaseFeed(ABC):
    title: str
    author: str
    origin_url: str
    logger: LoggerAdapter
    post_cls: type[FeedItem] = FeedItem

    def __init__(self):
        self.logger = NamespaceLogger(logger, {"source": self})

    @property
    @abstractmethod
    def namespace(self) -> str:
        """
        A unique identifier for this feed
        """
        pass

    @abstractmethod
    def update(self):
        """
        :param force: Force an update
        yield the sources that were updated
        """
        pass

    def post(self, post_id: str) -> Optional[FeedItem]:
        """mark"""
        cached = self.cache_get(post_id)
        if not cached:
            return None
        return from_dict(self.post_cls, cached)

    def posts(
        self, limit: int = 50, start: Optional[datetime] = None, end: Optional[datetime] = None
    ) -> list[FeedItem]:
        """
        Get the posts

        :param limit: Maximum number of posts to return (default 50)
        :param start: Only return posts modified after this time
        :param end: Only return posts modified before this time
        :return: A list of FeedItems
        """
        keys = self.cache_keys(limit=limit, start=start, end=end)
        posts: list[FeedItem] = []
        for key in keys:
            post = self.post(key)
            if post:
                posts.append(post)
        return posts

    def migrate(self):
        """
        Migrations of old data can only affect properties of feed items
        that are not part of the compound key.

        In other words, you can't change the namespace or id of a post
        because another feed may reference it.

        This migration corrects the mtime of all cached posts to match their posted_time.
        """

        # Get all keys without time filtering to migrate everything
        all_keys = global_config.cache.keys(self.namespace, limit=999999)
        migrated_count = 0

        for key in all_keys:
            if key == "meta":
                continue
            post_dict = self.cache_get(key)
            if post_dict and "posted_time" in post_dict:
                # Re-save to trigger mtime update
                self.cache_set(key, post_dict)
                migrated_count += 1

        self.logger.info(f"Migration complete: updated {migrated_count} posts")
        return True

    def cleanup(self):
        """
        Clean up any old data
        """
        return True

    def sources(self) -> Iterable["BaseFeed"]:
        """
        Get the sources. If the feed has sub-feeds, return them first
        so that this method is naturally topo-sorted.
        """
        yield from []

    @property
    def meta(self):
        return self.cache_get("meta") or {}

    @meta.setter
    def meta(self, obj: dict):
        meta = self.meta
        meta.update(obj)
        self.cache_set("meta", meta)

    @property
    def last_updated(self):
        last_updated_str = self.meta.get("last_updated", None)
        if last_updated_str:
            return datetime.fromisoformat(last_updated_str)
        return datetime.fromtimestamp(0, tz=timezone.utc)

    def set_last_updated(self, value: Optional[datetime] = None):
        value = value or utc_now()
        self.meta = {"last_updated": value.isoformat()}

    def next_update(self, force: bool) -> tuple[Optional[datetime], bool]:
        return None, False

    def lock(self):
        pass

    def unlock(self):
        pass

    @property
    def locked(self) -> bool:
        return False

    def __hash__(self):
        return hash(self.namespace)

    def __eq__(self, value):
        if self.__class__ == value.__class__:
            return self.namespace == value.namespace
        return False

    def cache_get(self, key: str) -> Optional[dict]:
        return global_config.cache.get(key, self.namespace)

    def cache_set(self, key: str, value: dict):
        if key != "meta":
            self.set_last_updated()
        return global_config.cache.set(key, value, self.namespace)

    def cache_delete(self, key: str):
        if key != "meta":
            self.set_last_updated()
        return global_config.cache.delete(key, self.namespace)

    def cache_keys(
        self, limit: int = 50, start: Optional[datetime] = None, end: Optional[datetime] = None
    ):
        return global_config.cache.keys(self.namespace, limit=limit, start=start, end=end)


class LockableBaseFeed(BaseFeed, ABC):
    @property
    def locked(self) -> bool:
        """Check if the feed is locked"""
        return self.meta.get("locked", False)

    def lock(self):
        """Lock the feed to prevent updates"""
        self.meta = {"locked": True}
        self.logger.warning(f"Feed locked - updates will be skipped")

    def unlock(self):
        """Unlock the feed to allow updates"""
        self.meta = {"locked": False}
        self.logger.info(f"Feed unlocked - updates are now allowed")


class ThrottleFeed(LockableBaseFeed, ABC):
    """
    A feed that is expensive to update, so it can be throttled to only update every interval.
    """

    interval: Optional[timedelta]

    def __init__(self, interval: Optional[timedelta], **kwargs):
        """
        :param interval: The minimum time between updates. If None, never auto-updates.
        """
        self.interval: Optional[timedelta] = interval
        super().__init__(**kwargs)

    @property
    def last_run(self) -> datetime:
        last_run_str = self.meta.get("last_run", None)
        if last_run_str:
            return datetime.fromisoformat(last_run_str)
        return datetime.fromtimestamp(0, tz=timezone.utc)

    def set_last_run(self, value: Optional[datetime] = None):
        # Library has minute resolution, round up to the next whole minute
        # to avoid running the same minute twice
        set_time = value or utc_now()
        set_time = (set_time + timedelta(minutes=1)).replace(second=0, microsecond=0)
        self.meta = {"last_run": set_time.isoformat()}

    def next_update(self, force: bool) -> tuple[Optional[datetime], bool]:
        """
        Return the next time this feed should be updated.
        Returns None if the feed has no interval configured.
        The returned time may be in the past if an update is overdue.
        """
        if self.locked and not force:
            self.logger.warning("Feed is locked - skipping update (use force=True to override)")
            return None, False
        if force:
            return utc_now() - self.interval, True
        if not self.interval:
            return None, False
        next_update = self.last_run + self.interval
        requires_update = next_update < utc_now()
        logfn = self.logger.info if requires_update else self.logger.debug
        next_run_str = next_update.strftime("%m-%d-%y %H:%M")
        last_run_str = self.last_run.strftime("%m-%d-%y %H:%M")
        logfn(f'last_run="{last_run_str}" next_run="{next_run_str}" needs_update={requires_update}')
        return next_update, requires_update


class AliasFeed(BaseFeed, ABC):
    """
    A feed that merely aliases another feed.
    Its purpose is to modify only the render side, not the update side.
    """

    name: Optional[str] = None
    source: BaseFeed
    post_cls: type[ReferenceFeedItem] = ReferenceFeedItem

    def __init__(self, source: BaseFeed):
        self.source = source
        self.title = source.title
        self.author = source.author
        self.origin_url = source.origin_url
        if self.name is None:
            raise TypeError("AliasFeed subclasses must define a 'name' property")
        super().__init__()

    @property
    def namespace(self):
        return f"{self.name}_{self.source.namespace}"

    def sources(self) -> Iterable[BaseFeed]:
        yield self.source

    @property
    def locked(self) -> bool:
        return self.source.locked

    def lock(self):
        self.source.lock()

    def unlock(self):
        self.source.unlock()

    @property
    def last_updated(self):
        return self.source.last_updated

    def update(self):
        self.source.update()

    def next_update(self, force):
        return self.source.next_update(force)

    def post(self, post_id: str) -> Optional[FeedItem]:
        """
        A bit convoluted, but we need to wrap the source post in a ReferenceFeedItem
        in order to hand back something that overrides the render method
        and preserves the subpost rendering.
        """
        subpost = self.source.post(post_id)
        if subpost is not None:
            return from_subpost(self.post_cls, subpost)
        return None

    def posts(
        self, limit: int = 50, start: Optional[datetime] = None, end: Optional[datetime] = None
    ) -> list[FeedItem]:
        posts = [
            self.post(post.id) for post in self.source.posts(limit=limit, start=start, end=end)
        ]
        return [post for post in posts if post is not None]


class AugmentFeed(BaseFeed, ABC):
    """
    A feed that augments another feed with additional data.
    """

    source: BaseFeed
    post_cls: type[ReferenceFeedItem] = ReferenceFeedItem
    name: str = "augment"
    limit: int

    def __init__(self, source: BaseFeed, limit: int = 10):
        self.source = source
        self.limit = limit
        self.author = source.author
        self.origin_url = source.origin_url
        self.title = source.title
        super().__init__()

    @property
    def namespace(self):
        return f"{self.name}_{self.source.namespace}"
    
    def sources(self) -> Iterable[BaseFeed]:
        yield self.source

    def next_update(self, force):
        source_next_update, source_needs_update = self.source.next_update(force)
        if self.source.last_updated >= self.last_updated:
            return self.source.last_updated, True
        return source_next_update, source_needs_update

