from datetime import datetime
from typing import Optional

from rss_glue.feeds import feed
from rss_glue.resources import global_config


class MergeFeed(feed.BaseFeed):
    """
    A merge feed is a simple time-based merge of multiple sources.
    """

    sources: list[feed.BaseFeed]
    name = "merge"
    id: str

    def __init__(self, id: str, *sources: feed.BaseFeed, title: str = "Merge Feed"):
        self.sources = list(sources)
        self.id = id
        self.title = title
        self.author = "RSS Glue"
        self.origin_url = global_config.base_url
        super().__init__()

    @property
    def namespace(self):
        return f"{self.name}_{self.id}"

    def update(self, force: bool = False) -> int:
        for source in self.sources:
            source.update(force)
        return 0

    def posts(self) -> list[feed.FeedItem]:
        sub_posts: list[feed.FeedItem] = []
        for source in self.sources:
            sub_posts.extend(source.posts())
        sub_posts.sort(key=lambda post: post.posted_time, reverse=True)

        return [
            feed.ReferenceFeedItem(
                version=0,
                namespace=self.namespace,
                id=f"{post.namespace}////{post.id}",
                author=post.author,
                title=post.title,
                posted_time=post.posted_time,
                subpost=post,
                origin_url=post.origin_url,
                discovered_time=post.discovered_time,
            )
            for post in sub_posts
        ]

    def post(self, post_id: str):
        namespace, post_id = post_id.split("////")
        for source in self.sources:
            if source.namespace == namespace:
                return source.post(post_id)
        return None
