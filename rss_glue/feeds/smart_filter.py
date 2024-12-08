from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Iterable, Optional, cast

from rss_glue.feeds import ai_client, feed

base_prompt = """
Please take a look at the following bit of a content from an RSS feed:

Title: {title}
Author: {author}
URL: {url}
Posted time: {posted_time}
Content: {content}

Decide if the post above is relevent based on the criteria expressed below:

"{prompt}"

Is this content relevent? Say 'yes' if the post is relevant, 'no' if it is not.
Don't say anything else.
"""


class HTMLFilter(HTMLParser):
    """
    A simple no deps HTML -> TEXT converter.
    @see https://stackoverflow.com/a/55825140
    """

    text = ""

    def handle_data(self, data):
        self.text += data


@dataclass
class AiFilterPost(feed.ReferenceFeedItem):

    token_cost: int
    include_post: bool


class AiFilterFeed(feed.BaseFeed):
    """
    AiFilterFeed is a feed that filters out posts based
    on a given prompt.
    """

    source: feed.BaseFeed
    limit: int
    client: ai_client.AiClient
    name: str = "smart_filter"
    post_cls: type[AiFilterPost] = AiFilterPost

    def __init__(
        self,
        source: feed.BaseFeed,
        client: ai_client.AiClient,
        prompt: str,
        content_limit: int = 1000,
        limit: int = -1,
        title: Optional[str] = None,
    ):
        self.source = source
        self.limit = limit
        self.prompt = prompt
        self.client = client

        self.author = source.author
        self.origin_url = source.origin_url
        self.content_limit = content_limit
        if title:
            self.title = title
        else:
            self.title = f"Filter {source.title}"
        super().__init__()

    @property
    def namespace(self):
        return f"{self.name}_{self.source.namespace}"

    def post(self, post_id) -> Optional[AiFilterPost]:
        cached = self.cache_get(post_id)
        if not cached:
            return None
        return self.post_cls(**self.post_cls.load(cached, self.source))

    def format_prompt(self, post: feed.FeedItem) -> str:
        f = HTMLFilter()
        f.feed(post.render())

        return base_prompt.format(
            title=post.title,
            author=post.author,
            content=f.text[: self.content_limit],
            url=post.origin_url,
            posted_time=post.posted_time.strftime("%Y-%m-%d %H:%M %Z"),
            prompt=self.prompt,
        )

    def posts(self) -> list[feed.FeedItem]:
        source_posts = self.source.posts()
        posts = [self.post(post.id) for post in source_posts]
        return [post for post in posts if post and post.include_post]

    def cleanup(self) -> None:
        cache_posts = cast(list[AiFilterPost], super().posts())
        source_post_keys = set([post.id for post in self.source.posts()])
        for post in cache_posts:
            # Remove posts that reference a post that no longer exists
            if not post.subpost:
                self.logger.info(
                    f"cleanup: removing {post.id} because it references a deleted post"
                )
                self.cache_delete(post.id)
            # Remove posts that wouldn't be included anymore
            if post.id not in source_post_keys:
                self.logger.info(
                    f"cleanup: removing {post.id} because it is no longer in the source"
                )
                self.cache_delete(post.id)

    def sources(self) -> Iterable[feed.BaseFeed]:
        yield self.source
        yield self

    def update(self, force: bool = False):
        """
        This feed only updates when the source feed updates
        """
        source_posts = self.source.posts()
        # Sort by posted_time
        source_posts.sort(key=lambda post: post.posted_time, reverse=True)
        # Limit to the user specified limit
        if self.limit != -1:
            source_posts = source_posts[: self.limit]
        # Figure out which ones we haven't tested yet

        for source_post in source_posts:
            post = self.post(source_post.id)
            if post:
                self.logger.debug(f" skipping filter check for {source_post.id}")
                continue

            msg = self.client.get_response(self.format_prompt(source_post))

            include_post = False
            if "yes" in msg.response.lower():
                include_post = True
            elif "no" in msg.response.lower():
                include_post = False
            else:
                self.logger.error(f"Invalid response: {msg.response}")

            value = self.post_cls(
                version=0,
                namespace=self.namespace,
                id=source_post.id,
                author=source_post.author,
                origin_url=source_post.origin_url,
                title=source_post.title,
                discovered_time=source_post.discovered_time,
                posted_time=source_post.posted_time,
                subpost=source_post,
                token_cost=msg.tokens_used,
                include_post=include_post,
            )
            self.logger.info(f"post={source_post.id} include_post={include_post}")
            self.cache_set(value.id, value.to_dict())
