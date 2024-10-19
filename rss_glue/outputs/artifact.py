from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple

from rss_glue.feeds.feed import BaseFeed


class Artifact(ABC):
    """
    An artifact of one or more feeds
    """

    sources: list[BaseFeed]

    def __init__(self, *sources: BaseFeed):
        self.sources = list(sources)

    @abstractmethod
    def generate(self) -> Iterable[Tuple[Path, datetime]]:
        pass


class MetaArtifact(Artifact, ABC):
    """
    An artifact of other artifacts
    """

    artifacts: list[Artifact]

    def __init__(self, *artifacts: Artifact):
        self.artifacts = list(artifacts)
        sources = []
        for artifact in artifacts:
            sources.extend(artifact.sources)
        super().__init__(*sources)
