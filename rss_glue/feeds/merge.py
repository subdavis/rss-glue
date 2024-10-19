from typing import Dict, Iterable

from rss_glue.feeds import feed
from rss_glue.resources import global_config


class MergeFeed(feed.BaseFeed):
    """
    A merge feed is a simple time-based merge of multiple sources.
    """

    _sources: list[feed.BaseFeed]
    name = "merge"
    id: str

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
        return self._sources

    def update(self, force: bool = False):
        # Merge has updated if any of the sources have updated
        last_updated = max([source.last_updated for source in self.sources()])
        if last_updated > self.last_updated or force:
            self.set_last_updated(last_updated)

    def posts(self) -> list[feed.FeedItem]:
        sub_posts_set: Dict[str, list[feed.FeedItem]] = {}
        for source in self._sources:
            for post in source.posts():
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
        parts = post_id.split("////")
        namespace = parts[0]
        post_id = "".join(parts[1:])
        for source in self._sources:
            if source.namespace == namespace:
                return source.post(post_id)
        return None
