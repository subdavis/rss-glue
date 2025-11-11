"""
Pytest configuration and fixtures for RSS Glue tests.

This module provides the two essential fixtures for testing RSS Glue:
1. fs_config - Sets up fake filesystem and global configuration
2. mock_http_requests - Enables httpretty for mocking HTTP requests

All feed-specific mocking should be done via helper functions in test_utils.py
"""

from pathlib import Path

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem

from rss_glue.feeds import feed
from rss_glue.resources import global_config


@pytest.fixture
def fs_config(fs: FakeFilesystem):
    """
    Configure global_config with a fake filesystem.

    This fixture sets up RSS Glue's global configuration to use
    the pyfakefs fake filesystem for isolated testing.

    Args:
        fs: The fake filesystem fixture from pyfakefs

    Returns:
        A configuration function that can be called to set up feeds
    """
    # Allow access to real test fixtures directory
    import pathlib

    fixtures_dir = pathlib.Path(__file__).parent / "fixtures"
    fs.add_real_directory(fixtures_dir, read_only=True)

    # Create a fake static root directory
    static_root = Path("/fake/static")
    fs.create_dir(static_root)

    # Configure global_config to use the fake filesystem
    # Set sleep_range to (0, 0) to disable sleeping in tests for speed
    global_config.configure(
        base_url="http://localhost:5000/",
        static_root=static_root,
        output_limit=12,
        sleep_range=(0, 0),
    )

    def configure(sources: list[feed.BaseFeed]):
        """Helper to reconfigure global_config with new sources."""
        global_config.configure(
            base_url="http://localhost:5000/",
            static_root=static_root,
            output_limit=12,
            sleep_range=(0, 0),
        )

        class Config:
            sources = []

            def __init__(self):
                self.sources = sources

        # Simulate load()
        global_config.__setattr__("_config", Config())
        global_config.collect_sources()

    yield configure

    # Cleanup - the pyfakefs fixture will handle filesystem cleanup


@pytest.fixture
def mock_http_requests():
    """
    Enable httpretty for mocking HTTP requests.

    This fixture enables httpretty at the start of a test and cleans up
    at the end. Individual tests should use helper functions from test_utils.py
    to register specific HTTP mocks.

    Example:
        def test_something(fs_config, mock_http_requests):
            mock_rss_feed()  # Register RSS feed mock
            # ... rest of test
    """
    import httpretty

    # Enable httpretty
    httpretty.enable(allow_net_connect=False)

    yield

    # Cleanup
    httpretty.disable()
    httpretty.reset()
