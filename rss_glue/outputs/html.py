from pathlib import Path
from typing import Iterable

from rss_glue import utils
from rss_glue.logger import logger
from rss_glue.outputs import artifact
from rss_glue.resources import global_config

# CSS should be a 500 pixel wide central column
page_css = """
body {
    font-family: Arial, sans-serif;
    margin: auto;
    width: 600px;
    max-width: 100%;
    background-color: #f0f0f0;
}
main {
    padding: 2em;
}
"""

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
    <main>
        <header>
            <a href="{origin_url}">
                <h1>{title}</h1>
            </a>
            <p>by {author}</p>
        </header>
        <article>
            {content}
        </article>
    </main>
</body>
</html>
"""

post_template = """
            <section>
                <a href="{origin_url}"><h2>{title}</h2></a>
                <time>{posted_time}</time>
                <div style="padding: 1em 0" >{content}</div>
                <hr>
            </section>
"""


class HtmlOutput(artifact.Artifact):

    def generate(self) -> Iterable[Path]:
        """
        Generate a single HTML page with all the posts from the sources
        """
        for source in self.sources:

            posts = source.posts()
            posts = sorted(posts, key=lambda x: x.posted_time, reverse=True)

            html = ""
            for post in posts:
                html += post_template.format(
                    title=post.title,
                    content=post.render(),
                    posted_time=post.posted_time.strftime(utils.human_strftime),
                    origin_url=post.origin_url,
                )
            html = page_template.format(
                title=source.title,
                author=source.author,
                origin_url=source.origin_url,
                content=html,
                css=page_css,
            )
            yield global_config.file_cache.write(source.namespace, "html", html, "html")
