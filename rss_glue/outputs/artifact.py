from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable

from rss_glue.feeds.feed import BaseFeed


class Artifact(ABC):
    sources: list[BaseFeed]

    def __init__(self, *sources: BaseFeed):
        self.sources = list(sources)

    @abstractmethod
    def generate(self) -> Iterable[Path]:
        pass
