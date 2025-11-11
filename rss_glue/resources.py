import atexit
import datetime
import hashlib
import importlib.util
import logging
import random as rand
import sys
import typing
from pathlib import Path
from time import sleep
from typing import Any, Callable, Dict

from rss_glue.cache import FileCache, JsonCache, MediaCache, SimpleCache
from rss_glue.logger import logger
from rss_glue.mongo_cache import MongoCache

if typing.TYPE_CHECKING:
    from rss_glue.feeds.feed import BaseFeed


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
    _media_cache: MediaCache
    static_root: Path
    base_url: str
    run_after_generate: Callable[[], None]
    output_limit: int
    mongo_url: str | None
    sources: list["BaseFeed"]
    source_map: Dict[str, "BaseFeed"]
    sleep_range: tuple[int, int] = (2, 4)

    def __init__(self):
        self._config = None
        self._browser = None
        self._pl = None
        self._page = None
        self._cache = None
        self._file_cache = None
        self._media_cache = None
        self.mongo_url = None
        self.sources = []
        self.source_map = {}

    def configure(
        self,
        base_url: str = "http://localhost:5000/",
        static_root: Path = Path.cwd() / "static",
        run_after_generate: Callable[[], None] = lambda: None,
        log_level: int = logging.INFO,
        output_limit: int = 12,
        mongo_url: str | None = None,
        sleep_range: tuple[int, int] = (2, 4),
    ):
        """
        :param base_url: The base URL to use for the generated RSS feeds
        :param static_root: The root directory to store static files
        :param run_after_generate: A function to run after generating the feeds
        :param log_level: The logging level to use
        :param output_limit: The maximum number of items to include in each output feed
        :param mongo_url: MongoDB connection string (e.g., "mongodb://user:pass@host:27017/")
                         If provided, uses MongoCache; otherwise uses JsonCache
        :param sleep_range: Tuple indicating min and max sleep time (in seconds) between requests
        """
        self.base_url = base_url
        self.static_root = static_root
        self.run_after_generate = run_after_generate
        self.output_limit = output_limit
        self.mongo_url = mongo_url
        self.sleep_range = sleep_range
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
        if type(rssconfig.sources) is not list:
            raise ValueError("Invalid config file: sources must be a list")

        self._config = rssconfig
        self.collect_sources()

    @property
    def cache(self) -> SimpleCache:
        if not self._cache:
            if self.mongo_url:
                self._cache = MongoCache(self.mongo_url)
            else:
                self._cache = JsonCache(self.static_root)
        return self._cache

    @property
    def file_cache(self) -> FileCache:
        if not self._file_cache:
            self._file_cache = FileCache(self.static_root)
        return self._file_cache

    @property
    def media_cache(self) -> MediaCache:
        if not self._media_cache:
            self._media_cache = MediaCache(self.static_root)
        return self._media_cache

    @property
    def root_sources(self) -> list["BaseFeed"]:
        """Get all feed sources from the config"""
        return self._config.sources if self._config else []

    def collect_sources(self) -> None:
        """
        Collect all sources including subsources recursively in topological order.
        Dependencies are visited before dependents (post-order DFS).
        This ensures child feeds are updated before parent feeds that depend on them.
        """
        source_map: Dict[str, "BaseFeed"] = {}
        topo_sorted: list["BaseFeed"] = []

        def _visit(source: "BaseFeed"):
            # Skip if already visited (handle shared dependencies)
            if source_map.get(source.namespace, False):
                logger.debug(f" Skipping already visited source: {source.namespace}")
                return

            source_map[source.namespace] = source
            logger.debug(f" Visiting source: {source.namespace} {source.__hash__()}")

            # Visit all dependencies first (post-order DFS)
            for subsource in source.sources():
                _visit(subsource)

            # Add this source after all its dependencies
            topo_sorted.append(source)
            logger.debug(f" Collected source: {source.namespace}")

        for source in self.root_sources:
            _visit(source)

        logger.info(f" Collected {len(topo_sorted)} unique sources")
        self.sources = topo_sorted
        self.source_map = source_map

    def by_namespace(self, namespace: str) -> "BaseFeed | None":
        return self.source_map.get(namespace, None)

    def sleep(self):
        sleep(rand.randint(self.sleep_range[0], self.sleep_range[1]))

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
