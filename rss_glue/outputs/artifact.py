from typing import Optional

from rss_glue.feeds.feed import BaseFeed


def filter_sources(sources: list[BaseFeed], limit: Optional[list[str]] = None) -> list[BaseFeed]:
    """
    Filter sources by namespace.

    Args:
        sources: List of feed sources
        limit: Optional list of namespaces to filter by

    Returns:
        Filtered list of sources
    """
    if limit is None or len(limit) == 0:
        return sources
    return [source for source in sources if source.namespace in limit]
