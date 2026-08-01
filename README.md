# RSS Glue v2

RSS feed **generator** and aggregator built with FastAPI, SQLModel, SQLite, and Jinja2. It is not a feed reader.

![RSS Glue Bottle Banner](./docs/banner.jpg)

## Features

RSSGlue is inspired by [RSSHub](https://github.com/diygod/rsshub), [Kill-the-newsletter](https://kill-the-newsletter.com/), and [Miniflux](https://miniflux.app/).

- **Schedules and caches updates.** Many feed generators (like RSSHub) just reach out to external sources on every fetch. For metered APIs or trigger-happy IP ban systems, this can cause problems. Get your news a little slower, it will be fine.
- **Social media aware.** Feed posts can set "score" (such as from up-vote & like counts) used to sort and filter downstream (such as in a "top" digest).
- **Extensible.** New feed sources take advantage of these features.
- **Rich media and formatting.** Feed generators can decide, for example, to include the top comment from a thread or embed metadata in the post body. Reddit's native feeds (for example) do not bother with rich embeddings and are generally unpleasant to read.
- **Cache images and enclosures.** Some feeds include images using reference links that expire or break quickly. RSSGlue will optionally cache discovered images.

### Supported Feed Sources

- Any RSS/Atom Feed
- Instagram Accounts ([Example](https://rssglue.subdavis.com/feed/ig-angrycatfish/html))
- Facebook Groups
- Email Newsletters
- Hackernews ([Example](https://rssglue.subdavis.com/feed/digest-hn/html))
- Reddit
- Wordpress ["MEC" Plugin Calendars](https://webnus.net/modern-events-calendar/)
- Wordpress ["The Events Calendar" Plugin Calendars](https://wordpress.org/plugins/the-events-calendar/)
- Squarespace Calendar API

## Configuration

| Variable                   | Description                                                        |
| -------------------------- | ------------------------------------------------------------------ |
| `ENABLE_BACKGROUND_WORKER` | `0` or `1`                                                         |
| `SECRET_KEY`               | For cookie signing, required                                       |
| `MEDIA_DIR`                | Path to media downloads                                            |
| `DISPLAY_TIMEZONE`         | Time zone for rendering times and interpreting cron schedules |

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

## Email feeds

An `email` feed turns messages delivered to one address into posts. All email
feeds share a single IMAP mailbox that you supply — RSS Glue never mints
addresses, so you set up plus-addressing (or a catch-all) with your own
provider.

1. In **Config → IMAP Inbox**, set the host, port, username and an **app
   password** (not your account password), then save.
2. Click **Test Connection**. It reports the message count and every folder it
   can see, which is the fastest way to catch a wrong password or folder name.
3. Create a feed of type `email` and give it an address such as
   `you+newsletter@example.com`. The form prefills it from the feed id.
4. Subscribe to the newsletter with that exact address.

| Setting             | Notes                                                                                       |
| ------------------- | ------------------------------------------------------------------------------------------- |
| Folder              | Defaults to `INBOX`. A provider-side filter into a dedicated folder scans much faster.       |
| Lookback (days)     | Each poll re-scans this window. Mail older than the window never appears, even after a reset. |
| Max message size    | Larger messages are skipped rather than downloaded. Defaults to 2 MiB.                        |

Matching happens client-side against `Delivered-To`, `X-Original-To`,
`Envelope-To`, `X-Forwarded-To`, `To`, `Cc`, `Bcc` and the `for <addr>` clause
of `Received` — Gmail's IMAP `SEARCH` normalizes plus-tags away, so it can't be
trusted for this. Messages are deduped by `Message-ID` and fetched with
`BODY.PEEK`, so nothing is ever marked read.

Attachments and inline `cid:` images are not rendered. Newsletter styling is
stripped by the shared HTML sanitizer, leaving text, links, tables and images.
Each post gets a permalink at `/post/{feed_id}/{external_id}`, which — like the
RSS endpoints — is readable without logging in.
