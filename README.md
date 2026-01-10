# RSS Glue v2

RSS feed aggregator and merger built with FastAPI, SQLModel, and Jinja2.

## Features

- Multiple feed sources: RSS/Atom, HackerNews, Instagram, Facebook
- Merge multiple feeds into one
- Digest feeds with cron scheduling
- Media caching (images, videos)
- JSON configuration with validation
- Server-rendered RSS and HTML output

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)

## Setup

```bash
# Install dependencies
uv sync

# Run the server
uv run uvicorn rss_glue.main:app --reload
```

The server runs at http://localhost:8000

## Usage

1. Go to http://localhost:8000/config
2. Add your feed configuration (see format below)
3. Click "Save Configuration"
4. Go to http://localhost:8000 to see your feeds
5. Click "Update All Feeds" to fetch posts
6. Click "HTML" or "RSS" next to any feed to view output

## Configuration Format

```json
{
  "cache_media": false,
  "feeds": [
    {
      "id": "hn-rss",
      "type": "rss",
      "name": "Hacker News RSS",
      "url": "https://news.ycombinator.com/rss",
      "limit": 50,
      "cache_media": true
    },
    {
      "id": "hn-api",
      "type": "hackernews",
      "name": "HN Top Stories",
      "story_type": "top",
      "limit": 30
    },
    {
      "id": "tech",
      "type": "merge",
      "name": "Tech Combined",
      "sources": ["hn-rss", "hn-api"],
      "limit": 100
    },
    {
      "id": "weekly",
      "type": "digest",
      "name": "Weekly Digest",
      "source": "tech",
      "schedule": "0 0 * * 0",
      "limit": 20
    }
  ]
}
```

## Feed Types

### rss - RSS/Atom feeds

Fetch posts from any RSS or Atom feed URL.

```json
{
  "id": "example",
  "type": "rss",
  "name": "Example Feed",
  "url": "https://example.com/feed.xml",
  "limit": 50,
  "cache_media": true
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier (alphanumeric, hyphens, underscores) |
| `type` | Yes | Must be "rss" |
| `name` | Yes | Display name |
| `url` | Yes | RSS/Atom feed URL |
| `limit` | No | Max posts to fetch (default: 50, max: 1000) |
| `cache_media` | No | Cache embedded images/videos (default: use global) |

### hackernews - Hacker News API

Fetch stories directly from HackerNews API.

```json
{
  "id": "hn",
  "type": "hackernews",
  "name": "HN Top",
  "story_type": "top",
  "limit": 30
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier |
| `type` | Yes | Must be "hackernews" |
| `name` | Yes | Display name |
| `story_type` | No | "top", "new", or "best" (default: "top") |
| `limit` | No | Max stories to fetch (default: 30, max: 500) |

### instagram - Instagram Graph API

Fetch posts from Instagram Business/Creator accounts.

```json
{
  "id": "my-ig",
  "type": "instagram",
  "name": "My Instagram",
  "user_id": "17841400000000000",
  "access_token": "EAAG...",
  "limit": 20
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier |
| `type` | Yes | Must be "instagram" |
| `name` | Yes | Display name |
| `user_id` | Yes | Instagram Business Account ID |
| `access_token` | Yes | Facebook Graph API access token |
| `limit` | No | Max posts to fetch (default: 20, max: 100) |

**Setup:**
1. Create a Facebook App at developers.facebook.com
2. Add Instagram Graph API product
3. Connect your Instagram Business/Creator account
4. Generate a long-lived access token
5. Get your Instagram Business Account ID from the API

### facebook - Facebook Page API

Fetch posts from Facebook Pages.

```json
{
  "id": "my-page",
  "type": "facebook",
  "name": "My FB Page",
  "page_id": "123456789",
  "access_token": "EAAG...",
  "limit": 20
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier |
| `type` | Yes | Must be "facebook" |
| `name` | Yes | Display name |
| `page_id` | Yes | Facebook Page ID |
| `access_token` | Yes | Page Access Token |
| `limit` | No | Max posts to fetch (default: 20, max: 100) |

**Setup:**
1. Create a Facebook App at developers.facebook.com
2. Add Facebook Login product
3. Request pages_read_engagement permission
4. Generate a Page Access Token for the target page

### merge - Combine feeds

Merge posts from multiple source feeds into one.

```json
{
  "id": "combined",
  "type": "merge",
  "name": "All Feeds",
  "sources": ["feed1", "feed2", "feed3"],
  "limit": 100
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier |
| `type` | Yes | Must be "merge" |
| `name` | Yes | Display name |
| `sources` | Yes | Array of feed IDs to merge |
| `limit` | No | Max posts in output (default: 100, max: 1000) |

### digest - Periodic rollups

Create periodic digest issues from a source feed.

```json
{
  "id": "weekly",
  "type": "digest",
  "name": "Weekly Digest",
  "source": "combined",
  "schedule": "0 0 * * 0",
  "limit": 20
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier |
| `type` | Yes | Must be "digest" |
| `name` | Yes | Display name |
| `source` | Yes | Source feed ID |
| `schedule` | Yes | Cron expression (e.g., "0 0 * * 0" for weekly) |
| `limit` | No | Max posts per digest (default: 20, max: 1000) |

## Global Settings

| Field | Default | Description |
|-------|---------|-------------|
| `cache_media` | false | Cache embedded media from all feeds |

## Media Caching

When enabled, media (images, videos) embedded in posts are downloaded and served locally.

- Enable globally: Set `"cache_media": true` at the root config level
- Enable per-feed: Set `"cache_media": true` on individual RSS feeds
- Per-feed setting overrides global setting

Cached media is stored in the `media/` directory.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Feed list page |
| GET | `/config` | Config editor page |
| POST | `/config` | Save configuration |
| GET | `/feed/{id}/html` | HTML preview for a feed |
| GET | `/feed/{id}/rss` | RSS output for a feed |
| POST | `/feed/{id}/update` | Update a single feed |
| POST | `/update` | Update all feeds |
| GET | `/media/{path}` | Serve cached media |

## Validation Rules

- Feed IDs must be unique
- Feed IDs must be alphanumeric with hyphens and underscores only
- Merge/digest feeds can only reference existing feed IDs
- Circular dependencies are not allowed
- Cron expressions must be valid

## Development

```bash
# Install dev dependencies
uv sync --all-extras

# Run tests
uv run pytest
```

## Database

SQLite database stored in `rss_glue.db`. Tables are created automatically on first run.

To reset the database, delete the file:

```bash
rm rss_glue.db
```
