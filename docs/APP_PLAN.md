# RSS Glue v2 Implementation Plan

## Overview

Build an RSS feed aggregator using **uv, FastAPI, SQLModel, Jinja2** with:
- JSON config as source of truth (synced to SQLite database)
- Server-rendered pages (no CSS)
- On-demand feed updates via POST endpoints

## Project Structure

```
rss-glue-2/
├── pyproject.toml
├── rss_glue/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── database.py             # SQLModel engine/session
│   ├── models/
│   │   ├── __init__.py
│   │   ├── db.py               # Database models (Feed, Post, etc.)
│   │   └── config.py           # Pydantic config validation
│   ├── feeds/
│   │   ├── __init__.py
│   │   ├── registry.py         # Feed type registry
│   │   ├── rss.py              # RSS feed handler
│   │   └── merge.py            # Merge feed handler
│   ├── services/
│   │   ├── __init__.py
│   │   ├── config_sync.py      # JSON config to DB sync
│   │   ├── update.py           # Feed update + topological sort
│   │   └── rss_output.py       # RSS XML generation
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── pages.py            # HTML page routes
│   │   ├── config.py           # Config API
│   │   └── feeds.py            # Feed/update routes
│   └── templates/
│       ├── base.html
│       ├── index.html
│       └── config.html
```

## Database Schema (SQLModel)

```python
# Feed - stores feed configuration
Feed(id: str PK, type: str, name: str, config: JSON, limit: int, created_at, updated_at)

# FeedRelationship - many-to-many for merge feeds
FeedRelationship(parent_feed_id: str PK FK, child_feed_id: str PK FK, position: int)

# Post - individual feed items
Post(id: int PK, feed_id: str FK, external_id: str, title, content, link, author, published_at, created_at)
  - Unique constraint on (feed_id, external_id)

# UpdateHistory - track updates
UpdateHistory(id: int PK, feed_id: str FK, started_at, completed_at, status, error_message, posts_added)
```

## JSON Config Format

```json
{
  "feeds": [
    {
      "id": "hn",
      "type": "rss",
      "name": "Hacker News",
      "url": "https://news.ycombinator.com/rss",
      "limit": 50
    },
    {
      "id": "tech",
      "type": "merge",
      "name": "Tech Feeds",
      "sources": ["hn", "xkcd"],
      "limit": 100
    }
  ]
}
```

**Validation rules:**
- Feed IDs must be unique, alphanumeric with `-_`
- URLs must be valid http/https
- Merge sources must reference existing feed IDs
- No circular dependencies (detect with DFS)

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List feeds (Jinja page) |
| GET | `/config` | Config editor page (textarea) |
| POST | `/config` | Save config, sync to DB |
| GET | `/feed/{id}/rss` | RSS XML output |
| POST | `/feed/{id}/update` | Update single feed |
| POST | `/update` | Update all feeds (topo order) |

## Key Implementation Details

### Feed Registry Pattern
```python
@FeedRegistry.register("rss")
class RssFeedHandler:
    @staticmethod
    def fetch(feed_id: str, config: dict, session) -> list[dict]:
        # Returns list of post dicts
```

### Topological Sort for Updates
- Merge feeds depend on their source feeds
- Use Kahn's algorithm to ensure sources update first
- Merge feeds don't fetch external data - they aggregate from DB at query time

### Merge Feed Behavior
- No stored posts - queries source feed posts at RSS generation time
- Deduplicates by (feed_id, external_id)
- Sorts by published_at descending

## Implementation Order

1. **Foundation**: pyproject.toml, database.py, models/db.py, models/config.py
2. **Feed Handlers**: feeds/registry.py, feeds/rss.py, feeds/merge.py
3. **Services**: services/config_sync.py, services/update.py, services/rss_output.py
4. **API**: main.py, routers/pages.py, routers/config.py, routers/feeds.py
5. **Templates**: base.html, index.html, config.html

## Dependencies (pyproject.toml)

```toml
dependencies = [
    "fastapi>=0.109.0",
    "uvicorn>=0.27.0",
    "sqlmodel>=0.0.14",
    "jinja2>=3.1.0",
    "feedparser>=6.0.0",
    "pydantic>=2.0.0",
]
```

## Verification

1. **Setup**: `uv sync && uv run uvicorn rss_glue.main:app --reload`
2. **Add config**: Go to `/config`, paste sample JSON, save
3. **Verify feeds listed**: Go to `/`, see feeds in table
4. **Trigger update**: Click "Update All Feeds" or POST `/update`
5. **Check RSS output**: Click RSS link or GET `/feed/{id}/rss`
6. **Verify merge**: Create merge feed, update, check combined RSS output

## Key Simplifications from v1

| v1 Problem | v2 Solution |
|------------|-------------|
| Deep inheritance hierarchy | Stateless handler functions with registry |
| Cache as feed type | Deferred (not in first pass) |
| AliasFeed/AugmentFeed wrappers | No wrappers - direct composition |
| ReferenceFeedItem indirection | Posts stored directly in DB |
| Python config with imports | JSON config with Pydantic validation |
| Filesystem JSON cache | SQLite database |
| Static generation | Server-rendered on request |
