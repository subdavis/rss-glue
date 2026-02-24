"""Custom feedgen extension for rssglue metadata in RSS output.

Adds a custom XML namespace to RSS entries for exposing post metadata
like score, source feed ID, and source feed type.
"""

from feedgen.ext.base import BaseExtension, BaseEntryExtension
from feedgen.util import xml_elem

RSSGLUE_NS = "https://github.com/subdavis/rss-glue/ns/1.0"


class RssGlueExtension(BaseExtension):
    """Feed-level extension that registers the rssglue namespace."""

    def extend_ns(self):
        return {"rssglue": RSSGLUE_NS}


class RssGlueEntryExtension(BaseEntryExtension):
    """Entry-level extension that writes metadata elements to RSS items."""

    def __init__(self):
        self.__metadata: dict = {}

    def metadata(self, value: dict | None = None) -> dict:
        if value is not None:
            self.__metadata = value
        return self.__metadata

    def extend_ns(self):
        return {"rssglue": RSSGLUE_NS}

    def extend_rss(self, feed):
        for key, value in self.__metadata.items():
            if value is not None:
                el = xml_elem("{%s}%s" % (RSSGLUE_NS, key), feed)
                el.text = str(value)
        return feed
