"""Shared HTTP client utilities with retry and browser-like headers."""

import httpx


def create_client(
    *,
    retries: int = 3,
    timeout: float = 30.0,
    extra_headers: dict | None = None,
) -> httpx.Client:
    """Create an httpx.Client with retry policy and browser-like headers.

    Args:
        retries: Number of retry attempts for transient errors.
        timeout: Default timeout in seconds.
        extra_headers: Optional dict of extra headers to merge with defaults.

    Returns:
        Configured httpx.Client instance.
    """
    default_headers = {
        "User-Agent": "RssGlue/2.0 by subdavis",
        "Accept": "application/json",
        "Connection": "keep-alive",
    }

    if extra_headers:
        default_headers.update(extra_headers)

    # httpx uses transport for retry configuration
    transport = httpx.HTTPTransport(retries=retries)

    return httpx.Client(
        timeout=timeout,
        headers=default_headers,
        transport=transport,
        follow_redirects=True,
    )


def create_async_client(
    *,
    retries: int = 3,
    timeout: float = 30.0,
    extra_headers: dict | None = None,
) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient with retry policy and browser-like headers.

    Args:
        retries: Number of retry attempts for transient errors.
        timeout: Default timeout in seconds.
        extra_headers: Optional dict of extra headers to merge with defaults.

    Returns:
        Configured httpx.AsyncClient instance.
    """
    default_headers = {
        "User-Agent": "RssGlue/2.0 by subdavis",
        "Accept": "application/json",
        "Connection": "keep-alive",
    }

    if extra_headers:
        default_headers.update(extra_headers)

    transport = httpx.AsyncHTTPTransport(retries=retries)

    return httpx.AsyncClient(
        timeout=timeout,
        headers=default_headers,
        transport=transport,
        follow_redirects=True,
    )
