"""Shared IMAP inbox access for `email` feeds.

One operator-supplied mailbox backs every email feed.  Each feed matches a
recipient address client-side against a shared, short-TTL scan of the recent
date window, so N feeds cost one login and one header fetch per update cycle.
"""

import email.policy
import hashlib
import html
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from typing import NamedTuple

from bs4 import BeautifulSoup
from imapclient import IMAPClient
from sqlmodel import Session

from rss_glue.models.db import SystemConfig

logger = logging.getLogger(__name__)

SCAN_TTL_SECONDS = 60
DEFAULT_MAX_MESSAGE_BYTES = 2 * 1024 * 1024

# Providers disagree on where the envelope recipient ends up.  Check them all;
# a plus-address survives in whichever one the provider happens to write.
RECIPIENT_HEADERS = (
    "delivered-to",
    "x-original-to",
    "envelope-to",
    "x-forwarded-to",
    "to",
    "cc",
    "bcc",
)
RECEIVED_FOR = re.compile(r"\bfor\s+<?([^\s<>;]+@[^\s<>;]+?)>?[\s;]*$", re.IGNORECASE)


class ImapSettings(NamedTuple):
    host: str
    port: int
    user: str
    password: str
    folder: str
    lookback_days: int
    max_bytes: int


class ScanEntry(NamedTuple):
    uid: int
    headers: EmailMessage
    internaldate: datetime
    size: int
    recipients: frozenset[str]


# ponytail: one module-global connection guarded by a single lock.  Updates are
# effectively serial (worker thread + occasional manual trigger), so contention
# is nil.  Move to a per-thread pool only if updates ever go parallel.
_lock = threading.Lock()
_client: IMAPClient | None = None
_client_key: tuple[str, int, str] | None = None
_scan: tuple[float, str, list[ScanEntry]] | None = None


def get_imap_settings(session: Session) -> ImapSettings | None:
    """Read IMAP credentials from SystemConfig, or None if unconfigured.

    Reads SystemConfig directly rather than via config_sync: handlers import
    this module, and config_sync pulls in every handler, which would be a cycle.
    """

    def value(key: str) -> str | None:
        row = session.get(SystemConfig, key)
        return row.value if row else None

    host, user, password = (
        value("imap_host"),
        value("imap_user"),
        value("imap_password"),
    )
    if not (host and user and password):
        return None
    return ImapSettings(
        host=host,
        port=int(value("imap_port") or 993),
        user=user,
        password=password,
        folder=value("imap_folder") or "INBOX",
        lookback_days=int(value("imap_lookback_days") or 7),
        max_bytes=int(value("imap_max_message_bytes") or DEFAULT_MAX_MESSAGE_BYTES),
    )


def _require_settings(session: Session) -> ImapSettings:
    settings = get_imap_settings(session)
    if settings is None:
        raise ValueError(
            "IMAP inbox is not configured. Set host, user and password under /config."
        )
    return settings


def _close() -> None:
    """Drop the cached connection and scan.  Caller must hold `_lock`."""
    global _client, _client_key, _scan
    if _client is not None:
        try:
            _client.logout()
        except Exception:
            pass
    _client = None
    _client_key = None
    _scan = None


def _get_client(settings: ImapSettings) -> IMAPClient:
    """Return a live client, reusing the cached one when it still responds."""
    global _client, _client_key
    key = (settings.host, settings.port, settings.user)
    if _client is not None and _client_key == key:
        try:
            _client.noop()
            return _client
        except Exception:
            logger.info("IMAP connection went stale, reconnecting")
    _close()
    client = IMAPClient(settings.host, port=settings.port, ssl=True)
    # Keep INTERNALDATE timezone-aware instead of naive-localtime.
    client.normalise_times = False
    client.login(settings.user, settings.password)
    _client = client
    _client_key = key
    return client


def _recipients(headers: EmailMessage) -> frozenset[str]:
    """Every address this message could plausibly have been delivered to."""
    raw: list[str] = []
    for name in RECIPIENT_HEADERS:
        raw.extend(str(h) for h in headers.get_all(name, []))
    addrs = {addr.lower() for _, addr in getaddresses(raw) if "@" in addr}

    for received in headers.get_all("received", []):
        match = RECEIVED_FOR.search(str(received))
        if match:
            addrs.add(match.group(1).lower())

    return frozenset(addrs)


def scan_window(session: Session) -> list[ScanEntry]:
    """Header-only scan of the recent date window, shared across all feeds."""
    global _scan
    settings = _require_settings(session)

    with _lock:
        now = time.monotonic()
        if (
            _scan is not None
            and _scan[1] == settings.folder
            and now - _scan[0] < SCAN_TTL_SECONDS
        ):
            return _scan[2]

        client = _get_client(settings)
        client.select_folder(settings.folder, readonly=True)
        since = date.today() - timedelta(days=settings.lookback_days)
        uids = client.search(["SINCE", since])

        entries: list[ScanEntry] = []
        if uids:
            response = client.fetch(
                uids, ["BODY.PEEK[HEADER]", "INTERNALDATE", "RFC822.SIZE"]
            )
            for uid, data in response.items():
                raw = data.get(b"BODY[HEADER]")
                if not raw:
                    continue
                headers = email.message_from_bytes(raw, policy=email.policy.default)
                entries.append(
                    ScanEntry(
                        uid=uid,
                        headers=headers,
                        internaldate=data[b"INTERNALDATE"],
                        size=data[b"RFC822.SIZE"],
                        recipients=_recipients(headers),
                    )
                )

        logger.info(
            "IMAP scan of %s since %s: %d messages",
            settings.folder,
            since,
            len(entries),
        )
        _scan = (now, settings.folder, entries)
        return entries


def fetch_message(session: Session, entry: ScanEntry) -> EmailMessage | None:
    """Full-fetch one message.  Returns None if it exceeds the size limit."""
    settings = _require_settings(session)
    if entry.size > settings.max_bytes:
        logger.warning(
            "Skipping IMAP uid %d: %d bytes exceeds limit of %d",
            entry.uid,
            entry.size,
            settings.max_bytes,
        )
        return None

    with _lock:
        client = _get_client(settings)
        client.select_folder(settings.folder, readonly=True)
        response = client.fetch([entry.uid], ["BODY.PEEK[]"])

    raw = response.get(entry.uid, {}).get(b"BODY[]")
    if not raw:
        logger.warning("IMAP uid %d disappeared before full fetch", entry.uid)
        return None
    return email.message_from_bytes(raw, policy=email.policy.default)


def test_connection(session: Session) -> str:
    """Connect, select the folder and report what we found (for setup checks)."""
    settings = _require_settings(session)
    with _lock:
        _close()  # force a fresh login so the test reflects current settings
        client = _get_client(settings)
        info = client.select_folder(settings.folder, readonly=True)
        folders = sorted(name for _, _, name in client.list_folders())
    return (
        f"Connected to {settings.host} as {settings.user}. "
        f"'{settings.folder}' holds {info.get(b'EXISTS', 0)} messages. "
        f"Available folders: {', '.join(folders)}"
    )


def _text_to_html(text: str) -> str:
    """Escape plain text and give it paragraph/line structure."""
    paragraphs = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [html.escape(line) for line in block.splitlines() if line.strip()]
        if lines:
            paragraphs.append("<p>" + "<br>".join(lines) + "</p>")
    return "".join(paragraphs)


def _clean_html(markup: str) -> str:
    """Drop inline `cid:` images (we don't render attachments) and tracking pixels."""
    soup = BeautifulSoup(markup, "html.parser")
    for img in soup.find_all("img"):
        src = str(img.get("src") or "").strip().lower()
        if (
            src.startswith("cid:")
            or str(img.get("width") or "") in ("0", "1")
            or str(img.get("height") or "") in ("0", "1")
        ):
            img.decompose()
    return str(soup)


def _body_html(msg: EmailMessage) -> str:
    """Best-effort renderable body.  `get_body` resolves alternative/related."""
    body = msg.get_body(preferencelist=("html", "plain"))
    if body is None:
        return ""
    try:
        text = body.get_content()
    except (LookupError, UnicodeDecodeError):
        # Bogus or unknown charset — decode permissively rather than lose the mail.
        payload = body.get_payload(decode=True)
        text = (
            payload.decode("utf-8", errors="replace")
            if isinstance(payload, bytes)
            else ""
        )
    if not isinstance(text, str):
        return ""
    if body.get_content_subtype() == "html":
        return _clean_html(text)
    return _text_to_html(text)


def message_to_post(msg: EmailMessage, feed_id: str, entry: ScanEntry) -> dict:
    """Convert a fetched message into an update_feed() post dict."""
    message_id = str(msg.get("message-id") or "").strip()
    if message_id:
        seed = message_id
    else:
        seed = f"{msg.get('from')}|{msg.get('subject')}|{msg.get('date')}|{entry.uid}"
    external_id = hashlib.sha256(seed.encode("utf-8", "replace")).hexdigest()[:16]

    author = None
    from_addrs = getaddresses([str(h) for h in msg.get_all("from", [])])
    if from_addrs:
        name, addr = from_addrs[0]
        author = name or addr or None

    published = None
    raw_date = msg.get("date")
    if raw_date:
        try:
            published = parsedate_to_datetime(str(raw_date))
        except (TypeError, ValueError):
            published = None
    if published is None:
        published = entry.internaldate
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    # A sender with a broken clock shouldn't pin itself to the top forever.
    published = min(published.astimezone(timezone.utc), datetime.now(timezone.utc))

    return {
        "external_id": external_id,
        "title": str(msg.get("subject") or "").strip() or "(no subject)",
        "content": _body_html(msg),
        "link": f"__BASE_URL__/post/{feed_id}/{external_id}",
        "author": author,
        "published_at": published,
    }
