# RSS Glue v2

RSS feed aggregator and merger built with FastAPI, SQLModel, and Jinja2.

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)

## Configuration

| Variable                   | Description                                                        |
| -------------------------- | ------------------------------------------------------------------ |
| `ENABLE_BACKGROUND_WORKER` | `0` or `1`                                                         |
| `SECRET_KEY`               | For cookie signing, required                                       |
| `MEDIA_DIR`                | Path to media downloads                                            |
| `DISPLAY_TIMEZONE`         | Time zone for rendering times and also interpreting cron schedules |

## Setup

```bash
# Install dependencies
uv sync

# Show commands
poe help

# The server runs at http://localhost:8000 (and listens on all interfaces).
poe dev

# To run **only** the background worker with or without the web server:
poe worker
poe devworker
```

## Feed configuration

* `cooldown_minutes` will fetch a feed every n minutes
* `schedule` will fetch a feed for a cron schedule
* `cache_media` will toggle local media cache
* `limit` limits number of posts per feed
* `type` is one of `digest|facebook|hackernews|instagram|merge|reddit|rss|smart_filter|wordpress_mec_events|squareup_events`
* `id` must be unique. Changing ID = erasing and recreating feed.
* `tags` are useful for creating merge feeds