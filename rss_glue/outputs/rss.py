from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple

import pytz
from feedgen.feed import FeedGenerator

from rss_glue.outputs.artifact import Artifact
from rss_glue.resources import global_config, utc_now


class RssOutput(Artifact):
    title_max_length = 80

    def generate(self) -> Iterable[Tuple[Path, datetime]]:
        """
        Generate a single HTML page with all the posts from the sources
        """
        for source in self.sources:
            file_to_generate = global_config.file_cache.getPath(source.namespace, "xml", "rss")
            relpath = global_config.file_cache.getRelativePath(source.namespace, "xml", "rss")
            # If the source has updated since the mtime of the file, regenerate
            if file_to_generate.exists():
                last_modified = datetime.fromtimestamp(
                    file_to_generate.stat().st_mtime, tz=pytz.utc
                )
                if last_modified >= source.last_updated:
                    yield relpath, last_modified
                    continue

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
            yield global_config.file_cache.write(source.namespace, "xml", decoded, "rss"), utc_now()
