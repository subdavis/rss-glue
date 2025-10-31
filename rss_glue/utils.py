from typing import Iterable, Optional, TypeVar
import inspect

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

human_strftime = "%a, %b %d %I:%M %p"

# CSS should be a 500 pixel wide central column
page_css = """
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
    margin: 0;
    padding: 1rem;
    background: #1a1a1a;
    color: #e0e0e0;
}
main {
    padding: 2rem;
    max-width: 600px;
    margin: 0 auto;
}
header {
    max-width: 600px;
    margin-bottom: 2rem;
    margin: 0 auto;
}
header h1 {
    margin: 0;
    color: #fff;
}
header a {
    color: inherit;
    text-decoration: none;
}
header a:hover h1 {
    color: #60a5fa;
}
header p {
    margin: 0.5rem 0 0;
    color: #888;
}
article {
    background: #252525;
    padding: 1.5rem;
    margin-bottom: 1rem;
    border-radius: 8px;
}
article h2 {
    margin: 0 0 0.5rem;
    font-size: 1.25rem;
}
article a {
    color: #60a5fa;
    text-decoration: none;
}
article a:hover {
    text-decoration: underline;
}
section:not(:last-child) {
    margin-bottom: 3rem;
}
time, .post-author {
    color: #888;
    font-size: 0.875rem;
}
hr {
    display: none;
}
"""


class _TimeoutSession(requests.Session):
    """Requests Session that applies a default timeout to requests.

    This avoids accidentally hanging on slow connections while still allowing
    callers to override the timeout per-call.
    """

    def __init__(self, timeout: float = 10.0):
        super().__init__()
        self._default_timeout = timeout

    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", self._default_timeout)
        return super().request(*args, **kwargs)


def make_browser_session(
    *,
    retries: int = 3,
    backoff_factor: float = 0.3,
    status_forcelist: Iterable[int] = (500, 502, 503, 504),
    timeout: float = 10.0,
    extra_headers: Optional[dict] = None,
) -> requests.Session:
    """Create and return a requests.Session configured to look like a browser.

    The session includes a reasonable User-Agent, common Accept headers and a
    retry policy for transient server/network errors. The returned session
    applies a default timeout to requests but callers can override it by
    passing a timeout to individual request methods.

    Args:
        retries: number of retry attempts for idempotent requests.
        backoff_factor: backoff factor between retries.
        status_forcelist: HTTP status codes that should trigger a retry.
        timeout: default timeout (seconds) for requests made from this session.
        extra_headers: optional dict of extra headers to merge with defaults.

    Returns:
        Configured requests.Session instance.
    """

    session = _TimeoutSession(timeout=timeout)

    # Common headers to mimic a normal browser
    default_headers = {
        "User-Agent": ("RssGlue/1.2 by subdavis"),
        "Accept": "application/json",
        # "Accept-Language": "en-US,en;q=0.9",
        # Let servers know we can accept compressed content; requests will
        # transparently decode it.
        # "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    session.headers.update(default_headers)
    if extra_headers:
        session.headers.update(extra_headers)

    # Attach a retry policy for both http and https
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=frozenset(["HEAD", "GET", "OPTIONS"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


T = TypeVar("T")


def from_dict(cls: type[T], obj: dict) -> T:
    return cls(**{k: v for k, v in obj.items() if k in inspect.signature(cls).parameters})
