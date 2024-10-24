from pathlib import Path

from rss_glue.feeds import RedditFeed
from rss_glue.outputs import Artifact, HTMLIndexOutput, HtmlOutput
from rss_glue.resources import global_config

global_config.configure(
    playwright_root=Path("/var/playwright"),
)

artifacts: list[Artifact] = [
    HTMLIndexOutput(
        HtmlOutput(
            RedditFeed(
                "https://www.reddit.com/r/selfhosted.json",
                schedule="0 0 * * *",
            ),
        ),
    )
]
