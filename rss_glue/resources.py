import atexit
import datetime
import hashlib
import importlib.util
import logging
import random as rand
import sys
import typing
import zipfile
from pathlib import Path
from typing import Any, Callable

from rss_glue.cache import FileCache, JsonCache, SimpleCache
from rss_glue.logger import logger

if typing.TYPE_CHECKING:
    from rss_glue.outputs.artifact import Artifact


def utc_now():
    return datetime.datetime.now(tz=datetime.timezone.utc)


def short_hash_string(string):
    """
    Return a SHA-256 hash of the given string
    """
    return hashlib.sha256(string.encode("utf-8")).hexdigest()[:16]


class Config:
    _config: Any
    _cache: SimpleCache
    _file_cache: FileCache
    static_root: Path
    base_url: str
    run_after_generate: Callable[[], None]

    def __init__(self):
        self._config = None
        self._browser = None
        self._pl = None
        self._page = None
        self._cache = None
        self._file_cache = None

    def configure(
        self,
        base_url: str = "http://localhost:5000/",
        static_root: Path = Path.cwd() / "static",
        run_after_generate: Callable[[], None] = lambda: None,
        log_level: int = logging.INFO,
        headless: bool = True,
    ):
        """
        :param base_url: The base URL to use for the generated RSS feeds
        :param static_root: The root directory to store static files
        :param run_after_generate: A function to run after generating the feeds
        :param log_level: The logging level to use
        :param headless: Whether to run the browser in headless mode
        """
        self.base_url = base_url
        self.static_root = static_root
        self.run_after_generate = run_after_generate
        self.headless = headless
        logger.setLevel(log_level)

        if not base_url.endswith("/"):
            self.base_url += "/"

    def load(self, config: str) -> Any:
        spec = importlib.util.spec_from_file_location("rssconfig", config)
        if spec is None:
            raise ValueError("Invalid config file")

        rssconfig = importlib.util.module_from_spec(spec)
        sys.modules["rssconfig"] = rssconfig
        if spec.loader:
            spec.loader.exec_module(rssconfig)

        # Validate the config
        if type(rssconfig.artifacts) is not list:
            raise ValueError("Invalid config file: artifacts must be a list")

        self._config = rssconfig

    @property
    def cache(self) -> SimpleCache:
        if not self._cache:
            self._cache = JsonCache(self.static_root)
        return self._cache

    @property
    def file_cache(self) -> FileCache:
        if not self._file_cache:
            self._file_cache = FileCache(self.static_root)
        return self._file_cache

    @property
    def artifacts(self) -> list["Artifact"]:
        collected: list["Artifact"] = []

        def collect(artifacts: list["Artifact"]):
            for artifact in artifacts:
                collected.append(artifact)
                collect(getattr(artifact, "artifacts", []))

        collect(self._config.artifacts)
        return collected

    @property
    def loaded(self):
        return self.config is not None

    def close_browser(self):
        if self._browser and self._pl:
            self._page.close()
            self._browser.close()
            self._pl.stop()
            self._page = None
            self._browser = None
            self._pl = None


global_config = Config()


def at_exit():
    global_config.close_browser()


atexit.register(at_exit)
