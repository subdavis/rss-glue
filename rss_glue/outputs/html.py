from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple

import pytz

from rss_glue import utils
from rss_glue.feeds import feed
from rss_glue.logger import logger
from rss_glue.outputs import artifact
from rss_glue.resources import global_config, utc_now

page_template = """
<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
    <style>
        {css}
    </style>
</head>
<body>
    <header>
        <a href="{origin_url}">
            <h1>{title}</h1>
        </a>
        <p>by {author}</p>
    </header>
    <main>
       {content}
    </main>
</body>
</html>
"""

post_template = """
            <article>
                <a href="{origin_url}"><h2>{title}</h2></a>
                <div style="display: flex; justify-content: space-between;">
                    <span class="post-author">{author}</span>
                    <time>{posted_time}</time>
                </div>
                <div style="padding: 1em 0" >{content}</div>
                <hr>
            </article>
"""


class HtmlOutput(artifact.Artifact):

    namespace = "html"

    def generate(self, limit=None) -> Iterable[Tuple[Path, datetime]]:
        """
        Generate a single HTML page with all the posts from the sources
        """
        force = limit is not None
        for source in self.sourcesFor(limit):
            file_to_generate = global_config.file_cache.getPath(
                source.namespace, "html", self.namespace
            )
            relpath = global_config.file_cache.getRelativePath(
                source.namespace, "html", self.namespace
            )
            # If the source has updated since the mtime of the file, regenerate
            if file_to_generate.exists() and not force:
                last_modified = datetime.fromtimestamp(
                    file_to_generate.stat().st_mtime,
                    tz=pytz.utc,
                )
                if last_modified >= source.last_updated:
                    yield relpath, last_modified
                    continue

            posts = source.posts()
            posts = sorted(posts, key=lambda x: x.posted_time, reverse=True)

            html = ""
            for post in posts:
                html += post_template.format(
                    title=post.title,
                    content=post.render(),
                    author=post.author,
                    posted_time=post.posted_time.strftime(utils.human_strftime),
                    origin_url=post.origin_url,
                )
            html = page_template.format(
                title=source.title,
                author=source.author,
                origin_url=source.origin_url,
                content=html,
                css=utils.page_css,
            )
            yield global_config.file_cache.write(source.namespace, "html", html, "html"), utc_now()
