from pathlib import Path

from rss_glue.outputs import Artifact
from rss_glue.resources import global_config

global_config.configure(
    playwright_root=Path("/var/playwright"),
)

artifacts: list[Artifact] = []
