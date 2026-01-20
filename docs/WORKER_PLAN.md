# Background Worker Implementation Plan

## Overview

Implement a background worker that automatically updates feeds based on per-feed schedules. The worker runs as an asyncio task within the FastAPI application lifecycle, controlled by an environment variable.

## Key Design Decisions

### 1. Dependency Handling Strategy

**Requirement**: "If the feed you're going to update has dependencies, update them first."

**Implementation**: When a feed is due for update, recursively collect all its dependencies and update them first, even if they're not individually due.

**Example**: Weekly digest with daily source feed
- Digest runs weekly (cron: `0 0 * * 0`)
- Source has 24h cooldown
- When digest is due (Sunday), worker updates source first (even if only 12h since last update)
- Ensures digest always has fresh data

**Algorithm**:
1. Find feeds where `next_update <= current_time`
2. For each due feed, collect all dependencies recursively via FeedRelationship
3. Build set of feeds to update (due + dependencies)
4. Topologically sort this set
5. Update in dependency order with `force=True`

### 2. Update Timing per Feed Type

**Regular feeds** (rss, hackernews, instagram, facebook, reddit):
- Use `cooldown_minutes` field
- `next_update = updated_at + cooldown_minutes`
- If `cooldown_minutes = 0` or `None`: manual-only (no auto-update)
- If never updated (`updated_at = None`): schedule immediately

**Merge feeds**:
- Always update, ignore cooldown.

**Digest feeds**:
- Use cron `schedule` from config (ignore cooldown_minutes)
- `next_update = croniter.get_next()` from last update time
- If `schedule` invalid/missing: manual-only

### 3. Environment Variable

**Name**: `ENABLE_BACKGROUND_WORKER`
**Behavior**: Opt-in (worker disabled by default)
**Values**: `true`, `1`, `yes` enable worker; anything else disables

### 4. Startup Behavior

**No immediate updates** - calculate next update times and sleep
- Prevents startup storms
- Predictable scheduling
- Respects cooldowns

### 5. Error Handling

**Strategy**: Log and continue
- Errors logged to `UpdateHistory` with status `"error"`
- Worker calculates next update as if succeeded
- Individual feed errors don't crash worker
- 10-second pause after worker-level errors before retry

## Implementation Steps

### Step 1: Create Background Worker Service

**New file**: `rss_glue/services/background_worker.py`

**Key functions**:

```python
calculate_next_update(feed: Feed, session: Session) -> Optional[datetime]
    """Calculate when feed should next update. Returns None for manual-only."""

get_feed_dependencies(feed_id: str, session: Session) -> list[str]
    """Recursively get all dependencies of a feed."""

get_feeds_to_update(session: Session) -> list[str]
    """Get feeds to update (due + dependencies) in topological order."""

calculate_next_wake_time(session: Session) -> Optional[datetime]
    """Calculate earliest next_update across all feeds."""

async def run_update_cycle(shutdown_event: asyncio.Event) -> int
    """Run one update cycle. Returns number of feeds updated."""

async def background_worker_loop(shutdown_event: asyncio.Event)
    """Main worker loop."""

async def start_background_worker()
    """Start worker if ENABLE_BACKGROUND_WORKER=true."""

async def stop_background_worker()
    """Gracefully stop worker."""
```

**Worker loop algorithm**:
```
WHILE not shutdown:
    1. get_feeds_to_update(session)
       - Find feeds where next_update <= now
       - For each, recursively collect dependencies
       - Build set of all feeds to update
       - Filter to topological order

    2. For each feed in order:
       - update_feed(feed_id, session, force=True)
       - Catch errors, log to UpdateHistory, continue

    3. calculate_next_wake_time(session)
       - Get minimum next_update across all feeds
       - If None, default to 5 minutes

    4. Sleep until next_wake or shutdown
       - Use asyncio.wait_for() with timeout
       - Break on shutdown event
```

**Key implementation details**:
- All DB operations in `asyncio.to_thread()` (SQLModel is sync)
- Use `datetime.now(timezone.utc)` for all time calculations
- Digest feeds: use `croniter(schedule, updated_at).get_next(datetime)`
- Global variables: `_worker_task`, `_shutdown_event` for lifecycle

### Step 2: Integrate with FastAPI Lifespan

**File**: `rss_glue/main.py`

**Changes**:
```python
from rss_glue.services.background_worker import (
    start_background_worker,
    stop_background_worker,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    create_db_and_tables()
    await start_background_worker()  # NEW

    yield

    # Shutdown
    await stop_background_worker()  # NEW
```

### Step 3: Update Documentation

**File**: `README.md`

**Add section** after "Configuration Format":

```markdown
## Background Worker

RSS Glue can automatically update feeds using a background worker.

### Enabling the Worker

```bash
ENABLE_BACKGROUND_WORKER=true poe dev
```

### How It Works

- **Regular feeds**: Update based on `cooldown_minutes`
  - Set to 0 or omit for manual-only
  - Example: `"cooldown_minutes": 60` updates hourly

- **Digest feeds**: Update based on cron `schedule`
  - Example: `"schedule": "0 0 * * 0"` runs weekly

- **Dependencies**: Source feeds update before merge/digest feeds
  - Worker updates dependencies even if not individually due
  - Ensures fresh data for merged/digest outputs

### Configuration Examples

Per-feed cooldown:
```json
{
  "feeds": [
    {
      "id": "hn",
      "type": "rss",
      "url": "https://news.ycombinator.com/rss",
      "cooldown_minutes": 30
    }
  ]
}
```

Global default cooldown:
```json
{
  "default_cooldown_minutes": 60,
  "feeds": [...]
}
```

Manual-only feed:
```json
{
  "id": "manual-feed",
  "type": "rss",
  "url": "...",
  "cooldown_minutes": 0 // Or any number below 0
}
```
```

### Step 4: Add Logging

**File**: `rss_glue/main.py`

Add at module level:
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

**File**: `rss_glue/services/background_worker.py`

Replace all `print()` with:
```python
import logging
logger = logging.getLogger("rss_glue.background_worker")

logger.info("Background worker started")
logger.info(f"Updated {count} feeds")
logger.error(f"Error updating feed {feed_id}: {e}", exc_info=True)
```

## Edge Cases & Error Scenarios

### 1. Feed Deleted While Worker Running
- `update_feed()` raises `ValueError("Feed not found")`
- Worker catches, logs, continues with other feeds
- Next cycle recalculates without deleted feed

### 2. Invalid Cron Expression
- `calculate_next_update()` catches `croniter` exception
- Returns `None` (manual-only)
- Feed won't auto-update but manual updates still work

### 3. Database Locked (SQLite)
- SQLAlchemy handles retries automatically
- If persistent, error logged to UpdateHistory
- Worker continues to next cycle

### 4. Never-Updated Feeds
- If `updated_at = None` and `cooldown_minutes > 0`: schedule immediately
- If `updated_at = None` and digest: calculate from "one period ago"
- Ensures new feeds start updating quickly

### 5. Worker Shutdown During Update
- `asyncio.to_thread()` not cancellable mid-operation
- UpdateHistory shows `status="running"` with no `completed_at`
- Next startup reschedules normally (no corruption)

### 6. Manual Update While Worker Running
- Both use same `update_feed()` function
- SQLite handles concurrency via locks
- Manual update changes `updated_at`, worker recalculates next

### 7. Config Changes While Running
- Wake worker early when config changes
- Recalculate immediately instead of waiting for next cycle
- No restart needed

### 8. Very Short Cooldowns (< 1 minute)
- disallowed by config schema
- Worker will wake frequently (busy loop)
- Recommend minimum 5 minutes in documentation
- No technical limitation, but inefficient

### 9. All Feeds Manual-Only
- `calculate_next_wake_time()` returns `None`
- Worker sleeps 5 minutes, rechecks
- Allows feeds to be added via config

## Critical Files

### Files to Create
- `rss_glue/services/background_worker.py` - Worker implementation

### Files to Modify
- `rss_glue/main.py` - Lifespan integration, logging config
- `README.md` - Documentation for environment variable and usage

### Files to Reference (no changes needed)
- `rss_glue/services/update.py` - `update_feed()`, `topological_sort_feeds()`
- `rss_glue/services/config_sync.py` - Already handles `cooldown_minutes`
- `rss_glue/models/db.py` - Feed model, UpdateHistory model, FeedRelationship
- `rss_glue/feeds/digest.py` - Digest feed logic with croniter
- `rss_glue/database.py` - Database engine and session creation

## Testing & Verification

### Manual Testing Steps

1. **Worker disabled by default**:
   ```bash
   poe dev
   # Check logs: "Background worker disabled"
   ```

2. **Worker enabled**:
   ```bash
   ENABLE_BACKGROUND_WORKER=true poe dev
   # Check logs: "Background worker started"
   ```

4. **Digest feed runs on schedule**:
   - Create digest with `schedule: "*/5 * * * *"`
   - Verify update runs every 5 minutes

5. **Dependencies update first**:
   - Create RSS feed (30min cooldown) + merge feed (15min cooldown)
   - When merge is due, verify RSS updates first (even if not due)

6. **Manual-only feeds don't auto-update**:
   - Create feed with `cooldown_minutes: 0`
   - Verify it never appears in auto-update logs
   - Verify manual update still works

7. **Graceful shutdown**:
   - Start worker, then Ctrl+C
   - Check logs: "Stopping background worker..." → "Background worker stopped"
   - Verify shutdown within 5 seconds

8. **Error handling**:
   - Create feed with invalid URL
   - Verify UpdateHistory shows error status
   - Verify worker continues with other feeds

### Unit Tests (Future)

Not to be done right now.

## Configuration Schema

**No schema changes needed** - all fields already exist:
- `Feed.cooldown_minutes: Optional[int]` - already in DB model
- `Feed.updated_at: Optional[datetime]` - already in DB model
- `config.default_cooldown_minutes: int` - already in AppConfig
- Digest `schedule` field - already in feed config dict

`config_sync.py` already handles cooldown_minutes (lines 104-109, 156).

## Web UI

1. **Web UI for worker status**:
   - Show next scheduled update per feed on index page.
   - Worker running/stopped status on index page.
   - Recent update history

