from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

from rss_glue.outputs import artifact
from rss_glue.resources import global_config

page_template = """
<!DOCTYPE html>
<html>
<head>
    <title>RSS Glue Index</title>
    <meta http-equiv="Content-Type" content="text/html; charset="utf-8">
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
    </p>"""


class HTMLIndexOutput(artifact.Artifact):
    artifacts: list[artifact.Artifact]

    def __init__(self, *artifacts: artifact.Artifact):

        self.artifacts = list(artifacts)
        sources = []
        for artifact in artifacts:
            sources.extend(artifact.sources)
        super().__init__(*sources)

    def generate(self) -> Iterable[Path]:
        """
        Generate a single HTML page referencing all the other artifacts
        """

        html = ""
        for artifact in self.artifacts:
            html += f"<h2>{artifact.__class__.__name__}</h2>"
            for relpath in artifact.generate():
                actualPath = urljoin(global_config.base_url, relpath.as_posix())
                html += link_template.format(
                    url=actualPath,
                )
                yield relpath
        html = page_template.format(
            content=html,
        )

        yield global_config.file_cache.write("index", "html", html, "index")
