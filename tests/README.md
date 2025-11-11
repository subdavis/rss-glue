## Test Guidance

* Tests should NOT make assertions about what's on disk / in the cache.
* Tests should only verify that the feed classes correctly parse and return posts.
  * Or that the generated output is correct
* Tests must use the `cli._update` function to run the update cycle rather than calling `feed.update()` directly.
  * This ensures that the global configuration is used correctly.
* Combine tests where possible to reduce duplication. Tests that depend on the same fixtures can often be combined into a single test function with multiple assertions.
* Remove any tests that are redundant or do not add significant value.

## Utility and Fixture Guidance

* There are only 2 fixtures! fs_config and mock_http_requests.
* Everything else should be helper functions in test utils!

Each helper function should populate a mock http request with exactly one type of feed or api response.

GOOD example:

```python
def mock_rss_feed():
    """Mock an RSS feed response."""
    # Read from real filesystem since fixtures aren't in fake filesystem
    import pathlib

    fixture_path = pathlib.Path(__file__).parent / "fixtures" / "sample_rss_feed.xml"

    httpretty.register_uri(
        httpretty.GET,
        "https://example.com/feed.xml",,
        body=fixture_path.read_text(),
        content_type="application/rss+xml",
    )
```

GOOD exmaple:

```python
def register_reddit_image_mocks(count: int = 100):
    import pathlib

    fixture_path1 = pathlib.Path(__file__).parent / "fixtures" / "test_image_1.jpg"

    for i in range(count):
        httpretty.register_uri(
            httpretty.GET,
            f"https://i.redd.it/test_image_{i}.jpg",
            body=fixture_path1.read_bytes(),
            content_type="image/jpeg",
            status=200,
        )
```

BAD Example:

```python
@pytest.fixture
def sample_rss_xml() -> str:
    """Load the sample RSS feed XML fixture."""
    # Read from real filesystem since fixtures aren't in fake filesystem
    import pathlib

    fixture_path = pathlib.Path(__file__).parent / "fixtures" / "sample_rss_feed.xml"
    return fixture_path.read_text()
```

BAD example:

```python
@pytest.fixture
def mock_rss_feed(sample_rss_xml):
    """
    Mock network requests for feedparser using httpretty.

    Httpretty mocks at the socket level, so it works with any HTTP library
    including urllib (which feedparser uses internally).
    """
    import httpretty

    # Enable httpretty
    httpretty.enable(allow_net_connect=False)

    # Register the mock for our test URL
    httpretty.register_uri(
        httpretty.GET,
        "https://example.com/feed.xml",
        body=sample_rss_xml,
        content_type="application/rss+xml",
        status=200,
    )

    yield

    # Cleanup
    httpretty.disable()
    httpretty.reset()
```

BAD example:

```python
@pytest.fixture
def mock_hackernews_api(sample_hackernews_responses):
    """
    Mock network requests for HackerNews API using httpretty.
    """
    import json

    import httpretty

    # Enable httpretty
    httpretty.enable(allow_net_connect=False)

    # Register the mock for top stories list
    httpretty.register_uri(
        httpretty.GET,
        "https://hacker-news.firebaseio.com/v0/topstories.json",
        body=json.dumps(sample_hackernews_responses["stories"]),
        content_type="application/json",
        status=200,
    )

    # Register mocks for individual stories
    httpretty.register_uri(
        httpretty.GET,
        "https://hacker-news.firebaseio.com/v0/item/38734567.json",
        body=json.dumps(sample_hackernews_responses["story_1"]),
        content_type="application/json",
        status=200,
    )

    httpretty.register_uri(
        httpretty.GET,
        "https://hacker-news.firebaseio.com/v0/item/38734568.json",
        body=json.dumps(sample_hackernews_responses["story_2"]),
        content_type="application/json",
        status=200,
    )

    # Register mock for comments
    httpretty.register_uri(
        httpretty.GET,
        "https://hacker-news.firebaseio.com/v0/item/38734600.json",
        body=json.dumps(sample_hackernews_responses["comment"]),
        content_type="application/json",
        status=200,
    )

    httpretty.register_uri(
        httpretty.GET,
        "https://hacker-news.firebaseio.com/v0/item/38734700.json",
        body=json.dumps(sample_hackernews_responses["comment_2"]),
        content_type="application/json",
        status=200,
    )

    yield

    # Cleanup
    httpretty.disable()
    httpretty.reset()
```