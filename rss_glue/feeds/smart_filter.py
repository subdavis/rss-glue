from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Iterable, Optional, cast

from rss_glue.feeds import ai_client, feed
from rss_glue.utils import from_subpost

_base_prompt = """
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


class AiFilterFeed(feed.AugmentFeed):
    """
    AiFilterFeed is a feed that filters out posts based
    on a given prompt.
    """

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
        self.prompt = prompt
        self.client = client
        self.content_limit = content_limit

        super().__init__(source=source, limit=limit)

        if title:
            self.title = title
        else:
            self.title = f"Filter {source.title}"

    def posts(
        self, limit: int = 50, start: Optional[datetime] = None, end: Optional[datetime] = None
    ) -> list[feed.FeedItem]:
        source_posts = self.source.posts(limit=limit, start=start, end=end)
        posts = [cast(AiFilterPost, self.post(post.id)) for post in source_posts]
        return [post for post in posts if post and post.include_post]

    def _format_prompt(self, post: feed.FeedItem) -> str:
        f = HTMLFilter()
        f.feed(post.render())

        return _base_prompt.format(
            title=post.title,
            author=post.author,
            content=f.text[: self.content_limit],
            url=post.origin_url,
            posted_time=post.posted_time.strftime("%Y-%m-%d %H:%M %Z"),
            prompt=self.prompt,
        )

    def update(self) -> None:
        for source_post in self.source.posts(limit=self.limit):
            post = self.post(source_post.id)
            if post:
                self.logger.debug(f" skipping filter check for {source_post.id}")
                continue

            msg = self.client.get_response(self._format_prompt(source_post))

            include_post = False
            if "yes" in msg.response.lower():
                include_post = True
            elif "no" in msg.response.lower():
                include_post = False
            else:
                self.logger.error(f"Invalid response: {msg.response}")

            value = from_subpost(
                self.post_cls,
                source_post,
                namespace=self.namespace,
                token_cost=msg.tokens_used,
                include_post=include_post,
            )
            self.logger.info(f"post={source_post.id} include_post={include_post}")
            self.cache_set(value.id, value.to_dict())