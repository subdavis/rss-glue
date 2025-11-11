from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple

import pytz

from rss_glue import utils
from rss_glue.feeds.feed import BaseFeed
from rss_glue.logger import logger
from rss_glue.resources import global_config, utc_now

page_template = utils.load_template("html_page.html.jinja")
post_template = utils.load_template("html_post.html.jinja")


def generate_html(
    sources: list[BaseFeed], force: bool = False, limit: int = 20
) -> Iterable[Tuple[BaseFeed, Path, datetime]]:
    """
    Generate HTML pages for the given sources.

    Args:
        sources: List of feed sources to generate HTML for

    Yields:
        Tuples of (source, relative_path, modified_time) for each generated file
    """

    for source in sources:

        file_to_generate = global_config.file_cache.getPath(source.namespace, "html", "html")
        relpath = global_config.file_cache.getRelativePath(source.namespace, "html", "html")
        # If the source has updated since the mtime of the file, regenerate
        if file_to_generate.exists() and not force:
            last_modified = datetime.fromtimestamp(
                file_to_generate.stat().st_mtime,
                tz=pytz.utc,
            )
            if last_modified >= source.last_updated:
                yield source, relpath, last_modified
                continue

        posts = source.posts(limit=limit)
        posts = sorted(posts, key=lambda x: x.posted_time, reverse=True)

        html = ""
        for post in posts:

            html += post_template.render(
                title=post.title,
                content=post.render(),
                enclosure=post.enclosure.render() if post.enclosure else None,
                author=post.author,
                posted_time=post.posted_time.strftime(utils.human_strftime),
                origin_url=post.origin_url,
            )
        html = page_template.render(
            title=source.title,
            author=source.author,
            origin_url=source.origin_url,
            content=html,
            css=utils.page_css,
        )
        output_path = global_config.file_cache.write(source.namespace, "html", html, "html")
        yield source, output_path, utc_now()
