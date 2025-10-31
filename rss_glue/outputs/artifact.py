from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Tuple

from rss_glue.feeds.feed import BaseFeed


class Artifact(ABC):
    """
    An artifact of one or more feeds
    """

    sources: list[BaseFeed]
    namespace: str

    def __init__(self, *sources: BaseFeed):
        self.sources = list(sources)

    @abstractmethod
    def generate(self, limit: Optional[list[str]]) -> Iterable[Tuple[Path, datetime]]:
        pass

    def sourcesFor(self, namespaces: Optional[list[str]]) -> list[BaseFeed]:
        """
        Get the sources that match the given namespaces
        """
        if namespaces is None or len(namespaces) == 0:
            return self.sources
        return [source for source in self.sources if source.namespace in namespaces]


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
