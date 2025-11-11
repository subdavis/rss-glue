from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple
from urllib.parse import urljoin

from rss_glue import utils
from rss_glue.feeds.feed import BaseFeed
from rss_glue.outputs.html import generate_html
from rss_glue.outputs.opml import generate_opml
from rss_glue.outputs.rss import generate_rss
from rss_glue.resources import global_config, utc_now
from rss_glue.utils import page_css

page_template = utils.load_template("index_page.html.jinja")
link_template = utils.load_template("index_link.html.jinja")


def generate_index(
    html_outputs: list[Tuple[BaseFeed, Path, datetime]],
    rss_outputs: list[Tuple[BaseFeed, Path, datetime]],
    opml_outputs: list[Tuple[Path, datetime]],
) -> Iterable[Tuple[Path, datetime]]:
    """
    Generate a single index.html file linking to all generated outputs.

    Args:
        html_outputs: List of (source, relpath, modified_time) tuples from HTML generation
        rss_outputs: List of (source, relpath, modified_time) tuples from RSS generation
        opml_outputs: List of (relpath, modified_time) tuples from OPML generation

    Yields:
        Tuples of (relative_path, modified_time) for the index file
    """
    html = ""

    # Add HTML outputs
    html += "<h2>HTML Feeds</h2>"
    for source, relpath, modified in html_outputs:
        actualPath = urljoin(global_config.base_url, relpath.as_posix())
        modified_local = modified.astimezone()
        modified_str = modified_local.strftime("%a, %b %-d %I:%M %p")
        html += link_template.render(url=actualPath, title=source.title, modified=modified_str)

    # Add RSS & OPML outputs
    html += "<h2>RSS Feeds</h2>"
    for source, relpath, modified in rss_outputs:
        actualPath = urljoin(global_config.base_url, relpath.as_posix())
        modified_local = modified.astimezone()
        modified_str = modified_local.strftime("%a, %b %-d %I:%M %p")
        html += link_template.render(url=actualPath, title=source.title, modified=modified_str)

    html += "<h2>OPML Document</h2>"

    for relpath, modified in opml_outputs:
        actualPath = urljoin(global_config.base_url, relpath.as_posix())
        modified_local = modified.astimezone()
        modified_str = modified_local.strftime("%a, %b %-d %I:%M %p")
        html += link_template.render(url=actualPath, title="OPML Feed", modified=modified_str)

    # Create the index page
    html = page_template.render(
        content=html,
        css=page_css,
    )

    yield global_config.file_cache.write("index", "html", html, "index"), utc_now()
