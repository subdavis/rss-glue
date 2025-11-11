from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple
from urllib.parse import urljoin

from rss_glue import utils
from rss_glue.feeds.feed import BaseFeed
from rss_glue.resources import global_config, utc_now

opml_template = utils.load_template("opml.xml.jinja")
outline_template = utils.load_template("opml_outline.xml.jinja")


def generate_opml(
    rss_outputs: list[Tuple[BaseFeed, Path, datetime]],
) -> Iterable[Tuple[Path, datetime]]:
    """
    Generate a single OPML file listing all RSS feeds.

    Args:
        rss_outputs: List of (source, relpath, modified_time) tuples from RSS generation

    Yields:
        Tuples of (relative_path, modified_time) for the OPML file
    """
    outlines = []

    # Create OPML entries from RSS outputs
    for source, relpath, modified in rss_outputs:
        actualPath = urljoin(global_config.base_url, relpath.as_posix())
        outlines.append(
            outline_template.render(
                title=relpath.stem,
                xml_url=actualPath,
            )
        )

    # Generate the OPML file
    xml = opml_template.render(
        content="\n".join(outlines),
        title="RSS Glue Feeds",
        date_created=utc_now().isoformat(),
    )
    yield global_config.file_cache.write("opml", "xml", xml, "opml"), utc_now()
