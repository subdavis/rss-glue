import logging
import random
import random as rand
from datetime import timedelta
from time import sleep
from typing import Set
from urllib.parse import urljoin

import click

from rss_glue.feeds import feed
from rss_glue.logger import logger
from rss_glue.outputs import Artifact, artifact
from rss_glue.resources import global_config, utc_now


def _collect_sources(artifacts: list["artifact.Artifact"]) -> list[feed.BaseFeed]:
    sources: Set[feed.BaseFeed] = set()
    sorted: list[feed.BaseFeed] = []
    for artifact in artifacts:
        if not issubclass(artifact.__class__, Artifact):
            raise ValueError(
                f"You put something in the artifacts list that is not an artifact: {artifact}"
            )
        for source in artifact.sources:
            for subsource in source.sources():
                if subsource not in sources:
                    sources.add(subsource)
                    sorted.append(subsource)
    return sorted


def _generate(artifact: "artifact.Artifact", force: bool = False):
    now = utc_now()
    for path, modified in artifact.generate():
        if modified > now:
            full_url = urljoin(global_config.base_url, path.as_posix())
            logger.info(f" generated {full_url}")


def _update(artifacts: list["artifact.Artifact"], force: bool, limit: list[str] = []):
    sources = _collect_sources(artifacts)
    if len(limit):
        logger.info(f" updating {len(limit)} sources")
        sources = [source for source in sources if source.namespace in limit]
    else:
        logger.info(f" discovered {len(sources)} sources")

    now = utc_now()

    for source in sources:
        source.update(force)
        if source.last_updated > now:
            sleep(rand.randint(2, 4))

    for artifact in artifacts:
        _generate(artifact)

    global_config.close_browser()


@click.group()
@click.option(
    "--config",
    default="config.py",
    help="Path to config python script",
    type=click.Path(exists=True),
)
@click.option("--debug", is_flag=True)
def cli(config: str, debug: bool):
    global_config.load(config)
    if debug:
        logger.setLevel(logging.DEBUG)


@cli.command()
def migrate():
    for source in _collect_sources(global_config.artifacts):
        source.migrate()


@cli.command()
def cleanup():
    for source in _collect_sources(global_config.artifacts):
        source.cleanup()


@cli.command()
@click.option("--interval", default=60, help="Interval in minutes")
def watch(interval: int):
    while True:
        _update(global_config.artifacts, force=False)

        global_config.run_after_generate()
        next_run_time_local = (utc_now() + timedelta(minutes=interval)).astimezone()
        logger.info(
            f" watch: sleeping for {interval} minutes until {next_run_time_local.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        sleep(60 * interval)


@cli.command()
@click.option("--force", is_flag=True)
@click.option("--feed", multiple=True, help="Specify feeds to update", type=str)
def update(force: bool, feed: list[str]):
    _update(global_config.artifacts, limit=feed, force=force)


@cli.command()
def debug():
    from flask import Flask

    global_config.base_url = "http://localhost:5000/static/"
    static_root = global_config.static_root
    app = Flask(__name__, static_folder=static_root)

    _update(global_config.artifacts, force=False)

    app.run(debug=True)


@cli.command()
def install():
    # Install playwright extensions
    # from https://github.com/uBlockOrigin/uBOL-home/releases/latest
    global_config.install()
