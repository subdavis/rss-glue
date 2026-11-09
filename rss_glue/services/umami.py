"""Server-side Umami analytics: report every HTTP request to a configured Umami server.

Feed readers never run JavaScript, so the usual tracker script can't see RSS
fetches. Instead we post each request to Umami's /api/send ourselves, passing
the client's IP and User-Agent through so sessions and devices still resolve.
"""

import asyncio
import logging
import time
from urllib.parse import urlencode

import httpx
from fastapi import Request
from sqlmodel import Session

from rss_glue.database import engine
from rss_glue.models.db import SystemConfig
from rss_glue.services.auth import COOKIE_NAME

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(timeout=5.0)
# Keep references so in-flight sends aren't garbage collected.
_tasks: set[asyncio.Task] = set()


def _settings() -> tuple[str | None, str | None]:
    with Session(engine) as session:
        url, website = (
            row.value if (row := session.get(SystemConfig, key)) else None
            for key in ("umami_url", "umami_website_id")
        )
    return url, website


async def _send(payload: dict) -> None:
    # ponytail: two-row DB read per request; cache settings if traffic ever makes it matter
    url, website = await asyncio.to_thread(_settings)
    if not (url and website):
        return
    try:
        response = await _client.post(
            f"{url.rstrip('/')}/api/send",
            json={"type": "event", "payload": {**payload, "website": website}},
            # Older Umami versions ignore payload.userAgent and read the header.
            headers={"User-Agent": payload.get("userAgent") or "rss-glue"},
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Umami send failed: %s", e)


async def track(request: Request, call_next):
    """HTTP middleware: respond first, then report the request in the background."""
    if request.url.path.startswith("/static/"):
        return await call_next(request)

    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000)

    headers = request.headers
    # Never ship the API key to a third party.
    query = urlencode(
        [(k, v) for k, v in request.query_params.multi_items() if k != "api_key"]
    )
    route = request.scope.get("route")
    route_path = getattr(route, "path", None) or "unmatched"
    # Uvicorn only honors X-Forwarded-For from localhost by default, so read it directly.
    forwarded = headers.get("x-forwarded-for", "").split(",")[0].strip()
    ip = (
        forwarded
        or headers.get("x-real-ip")
        or (request.client.host if request.client else "")
    )

    payload = {
        "hostname": request.url.hostname,
        "url": request.url.path + (f"?{query}" if query else ""),
        "referrer": headers.get("referer"),
        "language": headers.get("accept-language", "").split(",")[0].split(";")[0],
        "ip": ip,
        "userAgent": headers.get("user-agent"),
        "tag": route_path,
        "data": {
            "method": request.method,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "route": route_path,
            **request.path_params,
            # Aggregators put subscriber counts in the raw UA ("Feedly/1.0 (...; 42 subscribers)").
            "user_agent": headers.get("user-agent", ""),
            "accept": headers.get("accept", ""),
            "content_type": response.headers.get("content-type", ""),
            "conditional": bool(
                headers.get("if-none-match") or headers.get("if-modified-since")
            ),
            # Presented credentials, not verified ones; enough to split you from the public.
            "credentials": bool(
                headers.get("x-api-key")
                or "api_key" in request.query_params
                or COOKIE_NAME in request.cookies
            ),
        },
    }
    # Umami rejects empty strings for url-ish fields; drop blanks.
    payload = {k: v for k, v in payload.items() if v}

    task = asyncio.create_task(_send(payload))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return response
