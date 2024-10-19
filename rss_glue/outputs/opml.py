from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple
from urllib.parse import urljoin

from rss_glue.outputs.artifact import MetaArtifact
from rss_glue.resources import global_config, utc_now

opml_template = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="1.0">
    <head>
        <title>{title}</title>
        <dateCreated>{date_created}</dateCreated>
    </head>
    <body>
        <outline title="RSS Glue Feeds" text="RSS Glue Feeds">
            {content}
        </outline>
    </body>
</opml>
"""

outline_template = """
<outline text="{title}" title="{title}" type="rss" xmlUrl="{xml_url}"/>
"""


class OpmlOutput(MetaArtifact):

    def generate(self) -> Iterable[Tuple[Path, datetime]]:

        outlines = []
        for artifact in self.artifacts:
            for relpath, modified in artifact.generate():
                actualPath = urljoin(global_config.base_url, relpath.as_posix())
                outlines.append(
                    outline_template.format(
                        title=relpath.stem,
                        xml_url=actualPath,
                    )
                )
                yield relpath, modified
        xml = opml_template.format(
            content="\n".join(outlines),
            title="RSS Glue Feeds",
            date_created=utc_now().isoformat(),
        )
        yield global_config.file_cache.write("opml", "xml", xml, "opml"), utc_now()
