from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple

import pytz
from feedgen.feed import FeedGenerator

from rss_glue.feeds.feed import BaseFeed
from rss_glue.resources import global_config, utc_now


def generate_rss(
    sources: list[BaseFeed], force: bool = False, limit: int = 20
) -> Iterable[Tuple[BaseFeed, Path, datetime]]:
    """
    Generate RSS feeds for the given sources.

    Args:
        sources: List of feed sources to generate RSS for

    Yields:
        Tuples of (source, relative_path, modified_time) for each generated file
    """
    for source in sources:
        file_to_generate = global_config.file_cache.getPath(source.namespace, "xml", "rss")
        relpath = global_config.file_cache.getRelativePath(source.namespace, "xml", "rss")
        # If the source has updated since the mtime of the file, regenerate
        if file_to_generate.exists() and not force:
            last_modified = datetime.fromtimestamp(file_to_generate.stat().st_mtime, tz=pytz.utc)
            if last_modified >= source.last_updated:
                yield source, relpath, last_modified
                continue

        posts = source.posts(limit=limit)
        posts = sorted(posts, key=lambda x: x.posted_time, reverse=True)

        fg = FeedGenerator()

        fg.id(f"rssglue:{source.namespace}")
        fg.title(source.title)
        fg.author({"name": source.author})
        fg.link(href=source.origin_url, rel="alternate")
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
            if post.enclosure:
                fe.enclosure(
                    url=post.enclosure.url,
                    length=post.enclosure.length,
                    type=post.enclosure.type,
                )
            fe.updated(post.discovered_time)
            if post.author:
                fe.author({"name": post.author})

        decoded = fg.atom_str(pretty=True).decode("utf-8")
        output_path = global_config.file_cache.write(source.namespace, "xml", decoded, "rss")
        yield source, output_path, utc_now()
