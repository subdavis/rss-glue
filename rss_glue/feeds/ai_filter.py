from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Optional

from rss_glue.feeds import ai_client, feed

base_prompt = """
Please take a look at the following bit of a content from an RSS feed:

Title: {title}
Author: {author}
URL: {url}
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
    name: str = "ai_filter"

    def __init__(
        self,
        source: feed.BaseFeed,
        client: ai_client.AiClient,
        prompt: str,
        content_limit: int = 1000,
        limit: int = -1,
    ):
        self.source = source
        self.limit = limit
        self.prompt = prompt
        self.client = client
        self.title = f"Filter {source.title}"
        self.author = source.author
        self.origin_url = source.origin_url
        self.content_limit = content_limit
        super().__init__()

    @property
    def namespace(self):
        return f"{self.name}_{self.source.namespace}"

    def post(self, post_id) -> Optional[AiFilterPost]:
        cached = self.cache_get(post_id)
        if not cached:
            return None
        return AiFilterPost(**AiFilterPost.load(cached, self.source))

    def format_prompt(self, post: feed.FeedItem):
        f = HTMLFilter()
        f.feed(post.render())

        return base_prompt.format(
            title=post.title,
            author=post.author,
            content=f.text[: self.content_limit],
            url=post.origin_url,
            prompt=self.prompt,
        )

    def posts(self) -> list[feed.FeedItem]:
        posts = super().posts()

        return [
            post
            for post in posts
            if isinstance(post, AiFilterPost) and post.include_post
        ]

    def update(self, force: bool = False) -> int:
        """
        This feed only updates when the source feed updates
        """
        self.logger.debug(f" updating {self.namespace}")
        self.source.update(force)
        source_posts = self.source.posts()
        # Sort by posted_time
        source_posts.sort(key=lambda post: post.posted_time, reverse=True)
        # Limit to the user specified limit
        if self.limit != -1:
            source_posts = source_posts[: self.limit]
        # Figure out which ones we haven't tested yet
        new_posts = []
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

            value = AiFilterPost(
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
            self.logger.info(
                f" {self.namespace} post={source_post.id} include_post={include_post}"
            )
            self.cache_set(value.id, value.to_dict())
            new_posts.append(value)
        return len(new_posts)
