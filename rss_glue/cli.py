import logging
import random as rand
import traceback
from datetime import timedelta
from time import sleep
from typing import Optional, Set
from urllib.parse import urljoin

import click

from rss_glue.feeds import feed
from rss_glue.logger import logger
from rss_glue.outputs import Artifact
from rss_glue.resources import global_config, utc_now


def _collect_sources(artifacts: list[Artifact]) -> list[feed.BaseFeed]:
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


def _generate(artifact: Artifact, limit: Optional[list[str]] = None):
    now = utc_now()
    for path, modified in artifact.generate(limit=limit):
        if modified > now:
            full_url = urljoin(global_config.base_url, path.as_posix())
            logger.info(f" generated {full_url}")


def _update(artifacts: list[Artifact], force: bool, limit: list[str] = []):
    sources = _collect_sources(artifacts)
    if len(limit):
        logger.info(f" updating {len(limit)} sources")
        sources = [source for source in sources if source.namespace in limit]
    else:
        logger.info(f" discovered {len(sources)} sources")

    now = utc_now()

    for source in sources:
        try:
            source.update(force)
            if source.last_updated > now:
                sleep(rand.randint(2, 4))
        except Exception as e:
            logger.critical(f" Source {source.namespace} failed to update: {e}")
            logger.critical(traceback.format_exc())

    for artifact in artifacts:
        try:
            _generate(artifact)
        except Exception as e:
            logger.critical(f" Artifact failed to generate: {e}")
            logger.critical(traceback.format_exc())

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
    from pathlib import Path

    from flask import Flask, abort, send_from_directory

    global_config.base_url = "http://localhost:5000/"
    app = Flask(__name__)

    # Intercept static file requests so we can generate artifacts on-demand
    @app.route("/<path:filename>")
    def _static_proxy(filename: str):
        try:
            logger.info(f" static request: {filename}")
            req_path = Path(filename)

            # If the request is namespaced like "html/<artifact>.html" try to
            # discover the corresponding source by artifact namespace (the
            # file stem) and regenerate any artifacts that include it.
            if len(req_path.parts) >= 2:
                artifact_ns_dir = req_path.parts[0]
                requested_stem = req_path.stem

                # Find the source feed that matches the requested stem
                sources = _collect_sources(global_config.artifacts)
                match = next((s for s in sources if s.namespace == requested_stem), None)

                if match:
                    # Regenerate any artifacts that include this source
                    for artifact in global_config.artifacts:
                        try:
                            if (
                                any(
                                    s.namespace == match.namespace
                                    for s in getattr(artifact, "sources", [])
                                )
                                and artifact.namespace == artifact_ns_dir
                            ):
                                logger.info(
                                    f" on-demand: generating artifact for source {match.namespace} {artifact.__class__.__name__}"
                                )
                                _generate(artifact, limit=[match.namespace])
                        except Exception as e:
                            logger.critical(f" on-demand artifact generation failed: {e}")
                            logger.critical(traceback.format_exc())

        except Exception as e:
            logger.critical(f" static proxy error: {e}")
            logger.critical(traceback.format_exc())

        # Serve the static file normally (may 404 if generation didn't produce it)
        try:
            return send_from_directory(global_config.static_root, filename)
        except Exception:
            abort(404)

    # Run a full update once at startup so things exist for first requests
    _update(global_config.artifacts, force=False)

    app.run(debug=True, host="0.0.0.0", port=5000)
