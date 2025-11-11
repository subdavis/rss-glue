from datetime import datetime
from typing import Dict, Iterable, Optional

from rss_glue.feeds import feed
from rss_glue.resources import global_config
from rss_glue.utils import from_subpost


class MergeFeed(feed.BaseFeed):
    """
    A merge feed is a simple time-based merge of multiple sources.
    """

    _sources: list[feed.BaseFeed]
    name = "merge"
    id_divider = "////"
    id: str
    post_cls: type[feed.ReferenceFeedItem] = feed.ReferenceFeedItem

    def __init__(self, id: str, *sources: feed.BaseFeed, title: str = "Merge Feed"):
        self._sources = list(sources)
        self.id = id
        self.title = title
        self.author = "RSS Glue"
        self.origin_url = global_config.base_url
        super().__init__()

    @property
    def namespace(self):
        return f"{self.name}_{self.id}"

    def sources(self) -> Iterable[feed.BaseFeed]:
        yield from self._sources

    def update(self):
        pass

    @property
    def last_updated(self):
        return max([source.last_updated for source in self.sources()])

    def posts(
        self, limit: int = 50, start: Optional[datetime] = None, end: Optional[datetime] = None
    ) -> list[feed.FeedItem]:
        sub_posts_set: Dict[str, list[feed.FeedItem]] = {}
        for source in self._sources:
            for post in source.posts(limit=limit, start=start, end=end):
                key = str(post.hashkey())
                if key not in sub_posts_set:
                    sub_posts_set[key] = [post]
                else:
                    self.logger.debug(f"Duplicate post: {post.title}")
                    sub_posts_set[key].append(post)
                    sub_posts_set[key].sort(key=lambda post: post.discovered_time)

        sub_posts = [post[0] for post in sub_posts_set.values()]
        sub_posts.sort(key=lambda post: post.posted_time, reverse=True)

        return [
            from_subpost(
                self.post_cls,
                post,
                namespace=self.namespace,
                id=self.id_divider.join([post.namespace, post.id]),
            )
            for post in sub_posts
        ]

    def post(self, post_id: str):
        parts = post_id.split(self.id_divider)
        namespace = parts[0]
        # Support merges of merges by preserving the rest of the ID
        post_id = "".join(parts[1:])
        for source in self._sources:
            if source.namespace == namespace:
                ## There's no need to return a reference post because
                ## This code does not augment render
                return source.post(post_id)
        return None
