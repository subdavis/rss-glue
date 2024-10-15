from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import pycron

from rss_glue.logger import logger
from rss_glue.resources import global_config, utc_now


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
        if type(self.discovered_time) is str:
            self.discovered_time = datetime.fromisoformat(self.discovered_time)
        if type(self.posted_time) is str:
            self.posted_time = datetime.fromisoformat(self.posted_time)

    def render(self) -> str:
        raise NotImplementedError("FeedItem cannot be rendered")

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
    A ReferenceFeedItem is a reference to another feed item.
    """

    subpost: FeedItem

    def render(self):
        return self.subpost.render()

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"subpost": self.subpost.id})
        return d

    @staticmethod
    def load(obj: dict, source: "BaseFeed"):
        obj["subpost"] = source.post(obj["subpost"])
        return obj


class BaseFeed(ABC):
    title: str
    author: str
    origin_url: str

    @abstractmethod
    def update(self, force: bool = False) -> int:
        """
        :param force: Force an update
        :return: The number of new posts
        """
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

    @abstractmethod
    def post(self, post_id: str) -> Optional[FeedItem]:
        pass

    @property
    def meta(self):
        return self.cache_get("meta") or {}

    @meta.setter
    def meta(self, obj: dict):
        meta = self.meta
        meta.update(obj)
        self.cache_set("meta", meta)

    @property
    @abstractmethod
    def namespace(self):
        """
        A unique identifier for this feed
        """
        pass

    def cache_get(self, key: str) -> Optional[dict]:
        return global_config.cache.get(key, self.namespace)

    def cache_set(self, key: str, value: dict):
        return global_config.cache.set(key, value, self.namespace)

    def cache_keys(self):
        return global_config.cache.keys(self.namespace)


class ScheduleFeed(BaseFeed, ABC):
    """
    A feed that is expensive to update, so it can be throttled to update on a certain schedule.
    """

    schedule: str

    def __init__(self, schedule: str, **kwargs):
        self.schedule = schedule
        super().__init__(**kwargs)

    @property
    def last_run(self) -> datetime:
        last_run_str = self.meta.get("last_run", None)
        if last_run_str:
            return datetime.fromisoformat(last_run_str)
        return datetime.fromtimestamp(0, tz=timezone.utc)

    def set_last_run(self, value: datetime = utc_now()):
        # Library has minute resolution, round up to the next whole minute
        # to avoid running the same minute twice
        value = (value + timedelta(minutes=1)).replace(second=0, microsecond=0)
        self.meta = {"last_run": value.isoformat()}

    def needs_update(self, force: bool) -> bool:
        if force:
            return True
        if self.last_run > utc_now():
            return False
        _requires_update = pycron.has_been(self.schedule, self.last_run, utc_now())
        logger.debug(
            f" {self.namespace} last_run={self.last_run} requires_update={_requires_update}"
        )
        return _requires_update
