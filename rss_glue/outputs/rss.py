from pathlib import Path
from typing import Iterable

from feedgen.feed import FeedGenerator

from rss_glue.logger import logger
from rss_glue.outputs.artifact import Artifact
from rss_glue.resources import global_config


class RssOutput(Artifact):
    title_max_length = 80

    def generate(self) -> Iterable[Path]:
        for source in self.sources:

            posts = source.posts()

            fg = FeedGenerator()
            feed_id = source.origin_url

            fg.id(feed_id)
            fg.title(source.title)
            fg.author({"name": source.author})
            fg.link(href=feed_id, rel="alternate")
            fg.language("en")

            for post in posts:
                html = post.render()
                fe = fg.add_entry()
                fe.id(post.id)
                fe.title(post.title)
                fe.link(href=post.origin_url)
                fe.content(
                    html,
                    type="html",
                )
                fe.published(post.posted_time)
                fe.updated(post.discovered_time)
                if post.author:
                    fe.author({"name": post.author})

            decoded = fg.atom_str(pretty=True).decode("utf-8")
            yield global_config.file_cache.write(
                source.namespace, "xml", decoded, "rss"
            )
