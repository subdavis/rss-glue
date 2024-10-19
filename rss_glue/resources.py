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
from urllib.request import urlretrieve

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from rss_glue.cache import FileCache, JsonCache, SimpleCache
from rss_glue.logger import logger

if typing.TYPE_CHECKING:
    from rss_glue.outputs.artifact import Artifact


def utc_now():
    return datetime.datetime.now(tz=datetime.timezone.utc)


def cron_randomize(val: str, seed: str) -> str:
    """
    predictably randomize a cron schedule
    Useful for evenly spreading out the load of multiple expensive feeds.
    """
    state = rand.getstate()
    rand.seed(seed)
    parts = val.split(" ")
    for i, part in enumerate(parts):
        match i:
            case 0:
                parts[i] = part.replace("r", str(rand.randint(0, 59)))
            case 1:
                parts[i] = part.replace("r", str(rand.randint(0, 23)))
            case 2:
                parts[i] = part.replace("r", str(rand.randint(1, 31)))
            case 3:
                parts[i] = part.replace("r", str(rand.randint(1, 12)))
            case 4:
                parts[i] = part.replace("r", str(rand.randint(0, 6)))
    sched = " ".join(parts)
    rand.setstate(state)
    return sched


def short_hash_string(string):
    """
    Return a SHA-256 hash of the given string
    """
    return hashlib.sha256(string.encode("utf-8")).hexdigest()[:16]


class Config:
    _config: Any
    _browser: Browser
    _pl: Playwright
    _page: Page
    _cache: SimpleCache
    _file_cache: FileCache
    static_root: Path
    playwright_root: Path
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
        playwright_root: Path = Path.cwd() / "playwright",
        run_after_generate: Callable[[], None] = lambda: None,
        log_level: int = logging.INFO,
        headless: bool = True,
    ):
        """
        :param base_url: The base URL to use for the generated RSS feeds
        :param static_root: The root directory to store static files
        :param playwright_root: The root directory for the playwright installation
        :param run_after_generate: A function to run after generating the feeds
        :param log_level: The logging level to use
        :param headless: Whether to run the browser in headless mode
        """
        self.base_url = base_url
        self.static_root = static_root
        self.playwright_root = playwright_root
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
        return self._config.artifacts

    @property
    def loaded(self):
        return self.config is not None

    @property
    def browser(self):
        if not self._pl:
            self._make_browser()
        return self._browser

    @property
    def page(self):
        if not self._page:
            self._page = self.browser.new_page()
        return self._page

    def install(self):
        ublock = "https://github.com/uBlockOrigin/uBOL-home/releases/download/uBOLite_2024.10.6.1334/uBOLite_2024.10.6.1334.chromium.mv3.zip"

        download_path = self.playwright_root / "extensions" / "uBOLite.chromium.mv3.zip"
        download_path.parent.mkdir(parents=True, exist_ok=True)
        urlretrieve(ublock, download_path)
        # Unzip the file
        with zipfile.ZipFile(download_path, "r") as zip_ref:
            zip_ref.extractall(self.playwright_root / "extensions" / "uBOLite.chromium.mv3")

    def _make_browser(self):
        playwright_path = self.playwright_root
        path_to_extension = playwright_path / "extensions" / "uBOLite.chromium.mv3"
        self._pl = sync_playwright().start()
        self._browser = self._pl.chromium.launch_persistent_context(
            str(playwright_path / "browser_data"),
            headless=self.headless,
            args=[
                f"--disable-extensions-except={path_to_extension}",
                f"--load-extension={path_to_extension}",
            ],
        )

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
