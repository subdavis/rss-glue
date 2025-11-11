import logging
import traceback
from datetime import datetime, timedelta
from time import sleep
from urllib.parse import urljoin

import click

from rss_glue.logger import logger
from rss_glue.outputs import filter_sources, generate_outputs
from rss_glue.resources import global_config, utc_now


def _generate(source_keys: list[str] = [], force: bool = False):
    """Generate all outputs for the given sources"""
    now = utc_now()
    sources = filter_sources(global_config.root_sources, source_keys)
    for path, modified in generate_outputs(
        sources=sources, force=force, output_limit=global_config.output_limit
    ):
        if modified > now:
            full_url = urljoin(global_config.base_url, path.as_posix())
            logger.info(f" generated {full_url}")


def _update(source_keys: list[str] = [], force: bool = False):
    """Update sources and generate outputs"""
    now = utc_now()
    sources = filter_sources(global_config.sources, source_keys)

    for source in sources:
        try:
            _, needs_update = source.next_update(force)
            if needs_update:
                source.update()
            if source.last_updated > now:
                global_config.sleep()

        except Exception as e:
            logger.critical(f" Source {source.namespace} failed to update: {e}")
            logger.critical(traceback.format_exc())
            logger.critical(f" Locking source {source.namespace} due to failures")
            source.lock()

    try:
        _generate(source_keys)
    except Exception as e:
        logger.critical(f" Generation failed: {e}")
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
def repair():
    for source in global_config.sources:
        source.migrate()


@cli.command()
def cleanup():
    for source in global_config.sources:
        source.cleanup()


@cli.command()
def watch() -> None:
    while True:
        _update()
        update_times = [source.next_update(False)[0] for source in global_config.sources]
        next_update_time = min([x for x in update_times if x is not None])
        time_to_sleep = next_update_time - utc_now()
        logger.info(
            f" watch: sleeping for {time_to_sleep.total_seconds() // 60} minutes until {next_update_time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        sleep(time_to_sleep.total_seconds())


@cli.command()
@click.option("--force", is_flag=True)
@click.option("--feed", multiple=True, help="Specify feeds to update", type=str)
def update(force: bool, feed: list[str]):
    _update(force=force, source_keys=feed)


@cli.command()
@click.option("--force", is_flag=True)
def generate(force: bool):
    _generate(force=force)


@cli.command()
def sources():
    sources = global_config.sources
    for source in sources:
        post_count = str(len(source.posts(limit=0))).ljust(4)
        lock_status = "🔒" if source.locked else "--"

        logger.info(
            f" updated @ {source.last_updated} {lock_status} {post_count} {source.__class__.__name__}#{source.namespace} -- {source.title}"
        )


@cli.command()
@click.argument("namespace", type=str)
def lock(namespace: str):
    """Lock a feed to prevent updates"""
    sources = global_config.sources
    source = next((s for s in sources if s.namespace == namespace), None)
    if not source:
        logger.error(f" Feed not found: {namespace}")
        return
    source.lock()


@cli.command()
@click.argument("namespace", type=str, default="")
def unlock(namespace: str | None):
    """Unlock a feed to allow updates"""
    sources = global_config.sources
    if namespace == "":
        for _source in sources:
            _source.unlock()
    else:
        src = next((s for s in sources if s.namespace == namespace), None)
        if not src:
            logger.error(f" Feed not found: {namespace}")
            return
        src.unlock()


@cli.command()
def debug():
    from pathlib import Path

    from flask import Flask, abort, send_from_directory

    sources = global_config.sources
    # Reverse the order so that root sources are discovered first
    sources.reverse()
    _update()
    global_config.base_url = "http://localhost:5000/"
    app = Flask(__name__)

    # Intercept static file requests so we can generate outputs on-demand
    @app.route("/<path:filename>")
    def _static_proxy(filename: str):
        try:
            logger.info(f" static request: {filename}")
            req_path = Path(filename)

            # If the request is namespaced like "html/<source>.html" try to
            # discover the corresponding source by namespace (the file stem)
            # and regenerate the outputs that include it.
            if len(req_path.parts) >= 2:
                requested_stem = req_path.stem

                # Find the source feed that matches the requested stem
                match = next((s for s in sources if s.namespace == requested_stem), None)

                if match:
                    for output in generate_outputs(
                        sources=[match], force=True, output_limit=global_config.output_limit
                    ):
                        logger.info(f"    generated output: {output}")

        except Exception as e:
            logger.critical(f" static proxy error: {e}")
            logger.critical(traceback.format_exc())

        # Serve the static file normally (may 404 if generation didn't produce it)
        try:
            return send_from_directory(global_config.static_root, filename)
        except Exception:
            abort(404)

    app.run(debug=True, host="0.0.0.0", port=5000)
