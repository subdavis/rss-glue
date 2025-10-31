from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from logging import LoggerAdapter
from typing import Iterable, Optional

from rss_glue.logger import logger
from rss_glue.resources import global_config, utc_now
from rss_glue.utils import from_dict


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

    def __post_init__(self):
        self.logger = NamespaceLogger(logger, {"source": self})
        if type(self.discovered_time) is str:
            self.discovered_time = datetime.fromisoformat(self.discovered_time)
        if type(self.posted_time) is str:
            self.posted_time = datetime.fromisoformat(self.posted_time)

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

    def render(self):
        return self.subpost.render()

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"subpost": self.subpost.id})
        return d

    def hashkey(self):
        return self.subpost.hashkey()

    @staticmethod
    def load(obj: dict, source: "BaseFeed"):
        """
        A reference feed has a load function which should take the contents of the
        raw JSON object kept in the cache and return a fully "hydrated" FeedItem
        which probably references other feed item(s).
        """
        obj["subpost"] = source.post(obj["subpost"])
        if not obj["subpost"]:
            logger.error(f"missing reference ns={obj['namespace']} subpost={obj['id']}")
        return obj


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
    def namespace(self):
        """
        A unique identifier for this feed
        """
        pass

    @abstractmethod
    def update(self, force: bool = False):
        """
        :param force: Force an update
        yield the sources that were updated
        """
        pass

    @abstractmethod
    def post(self, post_id: str) -> Optional[FeedItem]:
        pass

    def posts(self) -> list[FeedItem]:
        """
        Get the posts

        :return: A list of FeedItems
        """
        keys = self.cache_keys()
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
        """
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
        yield self

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

    def __hash__(self):
        return hash(self.namespace)

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

    def cache_keys(self):
        return global_config.cache.keys(self.namespace)


class ThrottleFeed(BaseFeed, ABC):
    """
    A feed that is expensive to update, so it can be throttled to only update every interval.
    """

    interval: timedelta

    def __init__(self, interval: timedelta, **kwargs):
        self.interval = interval
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

    def needs_update(self, force: bool) -> bool:
        if force:
            return True
        if self.last_run > utc_now():
            return False
        _requires_update = (self.last_run + self.interval) < utc_now()
        logfn = self.logger.info if _requires_update else self.logger.debug
        next_run_str = (self.last_run + self.interval).strftime("%m-%d-%y %H:%M")
        last_run_str = self.last_run.strftime("%m-%d-%y %H:%M")
        logfn(f'last_run="{last_run_str}" next_run="{next_run_str}" update={_requires_update}')
        return _requires_update


class ReferenceFeed(BaseFeed, ABC):
    """
    A feed that references another feed.
    Its purpose is to modify only the render side, not the update side.
    """

    source: BaseFeed
    post_cls: type[ReferenceFeedItem] = ReferenceFeedItem

    def __init__(self, source: BaseFeed):
        self.source = source
        self.title = source.title
        self.author = source.author
        self.origin_url = source.origin_url
        super().__init__()

    @property
    def namespace(self):
        return self.source.namespace

    def sources(self) -> Iterable[BaseFeed]:
        """
        Return the source feed first, then this feed.
        """
        # yield self.source # Hide the source from normal source collection
        yield self

    @property
    def last_updated(self):
        """
        The CacheFeed's last_updated is the source feed's last_updated.
        """
        return self.source.last_updated

    def update(self, force: bool = False):
        self.source.update(force=force)

    def post(self, post_id: str) -> Optional[FeedItem]:
        """
        Get a specific cached post by ID.
        """
        cached = self.cache_get(post_id)
        if not cached:
            return None

        cached["subpost"] = cached["id"]
        loaded = self.post_cls.load(cached, self.source)

        return from_dict(self.post_cls, loaded)
