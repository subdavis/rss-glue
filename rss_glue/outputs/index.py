from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple
from urllib.parse import urljoin

from rss_glue.feeds import feed
from rss_glue.outputs import artifact
from rss_glue.resources import global_config, utc_now
from rss_glue.utils import page_css

page_template = """
<!DOCTYPE html>
<html>
<head>
    <title>RSS Glue Index</title>
    <meta http-equiv="Content-Type" content="text/html; charset="utf-8">
    <style>
        {css}
    </style>
</head>
<body>
    <main>
        <header>
            <h1>RSS Glue Index</h1>
        </header>
        <article>
            {content}
        </article>
    </main>
</body>
</html>
"""

link_template = """
    <p>
        <a href="{url}">{url}</a>
        <p style="font-size: 10px">
    </p>"""


class HTMLIndexOutput(artifact.MetaArtifact):

    namespace = "index"

    def generate(self, limit=None) -> Iterable[Tuple[Path, datetime]]:

        html = ""
        for artifact in self.artifacts:
            html += f"<h2>{artifact.__class__.__name__}</h2>"
            for relpath, modified in artifact.generate(limit=limit):
                actualPath = urljoin(global_config.base_url, relpath.as_posix())
                html += link_template.format(
                    url=actualPath,
                )
                yield relpath, modified
        html = page_template.format(
            content=html,
            css=page_css,
        )

        yield global_config.file_cache.write("index", "html", html, self.namespace), utc_now()
