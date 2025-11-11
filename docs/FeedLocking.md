# Feed Locking Feature

## Overview

The feed locking feature allows you to prevent feeds from being updated automatically. This is useful when a feed requires manual intervention or when you want to temporarily disable updates for a specific feed.

## How It Works

When a feed is locked:
- A `locked: true` flag is added to the feed's metadata file
- Updates are skipped during normal `update` and `watch` operations
- A warning is logged when an update is attempted on a locked feed
- The lock can be overridden by using `force=True` (via the `--force` flag)

## Usage

### Locking a Feed

```bash
rss-glue --config config.py lock <namespace>
```

Example:
```bash
rss-glue --config config.py lock reddit_minneapolis
```

### Unlocking a Feed

```bash
rss-glue --config config.py unlock <namespace>
```

Example:
```bash
rss-glue --config config.py unlock reddit_minneapolis
```

### Viewing Lock Status

The lock status is displayed when listing sources:

```bash
rss-glue --config config.py sources
```

Output will show 🔒 for locked feeds and 🔓 for unlocked feeds:
```
🔒 2025-11-12 10:30:00+00:00 -- Reddit Minneapolis -- RedditFeed#reddit_minneapolis
🔓 2025-11-12 11:45:00+00:00 -- Hacker News -- HackerNewsFeed#hackernews_best
```

### Force Updating a Locked Feed

You can still force an update on a locked feed by using the `--force` flag:

```bash
rss-glue --config config.py update --force --feed <namespace>
```

Example:
```bash
rss-glue --config config.py update --force --feed reddit_minneapolis
```

## When to Use Feed Locking

1. **Manual Intervention Required**: When a feed needs debugging or manual fixes
2. **Temporary Disable**: When you want to temporarily stop updates without removing the feed from your configuration
3. **Rate Limiting**: When a feed source is having issues and you need to prevent repeated failed update attempts
4. **Development**: When testing other feeds and you want to skip updating certain expensive feeds

## Implementation Details

The lock is implemented at the base feed level, which means:
- All feed types support locking (RSS, Reddit, Instagram, Merge, Digest, etc.)
- The lock check happens early in the update process
- The lock state is persisted in the feed's metadata cache
- Locked feeds can still be read and generate outputs normally
- Only the update/refresh operation is blocked
