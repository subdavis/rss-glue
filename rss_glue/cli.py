import logging
from datetime import timedelta
from time import sleep
from urllib.parse import urljoin

import click

from rss_glue.logger import logger
from rss_glue.outputs import artifact
from rss_glue.resources import global_config, utc_now


def _generate(artifacts: list["artifact.Artifact"]):
    for artifact in artifacts:
        for path in artifact.generate():
            full_url = urljoin(global_config.base_url, path.as_posix())
            logger.info(f" generated {full_url}")


def _update(artifacts: list["artifact.Artifact"], force: bool):
    updated_namespaces_set = set()
    for artifact in artifacts:
        for source in artifact.sources:
            if not source.namespace in updated_namespaces_set:
                count = source.update(force)
                updated_namespaces_set.add(source.namespace)
                if count:
                    sleep(1)


@click.group()
@click.option(
    "--config",
    default="config.py",
    help="Path to config python script",
    type=click.Path(exists=True),
)
@click.option("--log-level", default="INFO", help="Log level")
def cli(config: str, log_level: str):
    logger.setLevel(logging.getLevelName(log_level))
    global_config.load(config)


@cli.command()
@click.option("--interval", default=60, help="Interval in minutes")
def watch(interval: int):
    while True:
        _update(global_config.artifacts, force=False)
        _generate(global_config.artifacts)
        global_config.close_browser()
        global_config.run_after_generate()
        next_run_time_local = (utc_now() + timedelta(minutes=interval)).astimezone()
        logger.info(
            f" watch: sleeping for {interval} minutes until {next_run_time_local.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        sleep(60 * 60)


@cli.command()
@click.option("--force", is_flag=True)
def update(force: bool):
    _update(global_config.artifacts, force=force)
    _generate(global_config.artifacts)


@cli.command()
def debug():
    from flask import Flask

    global_config.base_url = "http://localhost:5000/static/"
    static_root = global_config.static_root
    app = Flask(__name__, static_folder=static_root)

    _update(global_config.artifacts, force=False)
    _generate(global_config.artifacts)

    app.run(debug=True)


@cli.command()
def install():
    # Install playwright extensions
    # from https://github.com/uBlockOrigin/uBOL-home/releases/latest
    global_config.install()
