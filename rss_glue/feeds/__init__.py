"""Feed infrastructure for RSS Glue."""

import rss_glue.handlers as handlers  # noqa: F401 — triggers all handler registrations
from rss_glue.feeds.registry import FeedRegistry as FeedRegistry
