from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple

from rss_glue.feeds.feed import BaseFeed
from rss_glue.logger import logger

from .artifact import filter_sources
from .html import generate_html
from .index import generate_index
from .opml import generate_opml
from .rss import generate_rss


def generate_outputs(
    sources: list[BaseFeed], force: bool = False, output_limit: int = 12
) -> Iterable[Tuple[Path, datetime]]:
    """
    Coordinate generation of all outputs for the given sources.

    This is the main entry point for generating HTML, RSS, OPML, and index files.

    Args:
        sources: List of feed sources to generate outputs for

    Yields:
        Tuples of (relative_path, modified_time) for each generated file
    """

    # Generate HTML outputs
    html_outputs = list(generate_html(sources, force=force, limit=output_limit))
    for source, relpath, modified in html_outputs:
        yield relpath, modified

    # Generate RSS outputs
    rss_outputs = list(generate_rss(sources, force=force, limit=output_limit))
    for source, relpath, modified in rss_outputs:
        yield relpath, modified

    if force:
        return

    # Generate OPML
    opml_outputs = list(generate_opml(rss_outputs))
    for relpath, modified in opml_outputs:
        yield relpath, modified

    # Generate index
    for relpath, modified in generate_index(html_outputs, rss_outputs, opml_outputs):
        yield relpath, modified
