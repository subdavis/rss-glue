#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Upload a JSON feed config file to an RSS Glue server."""

import argparse
import json
import sys

import httpx


def main():
    parser = argparse.ArgumentParser(
        description="Upload a JSON feed config to an RSS Glue server"
    )
    parser.add_argument("server_url", help="Server URL (e.g., http://localhost:8000)")
    parser.add_argument("username", help="Username for authentication")
    parser.add_argument("password", help="Password for authentication")
    parser.add_argument("config_file", help="Path to JSON feed config file")
    args = parser.parse_args()

    # Normalize server URL
    server_url = args.server_url.rstrip("/")

    # Read config file
    try:
        with open(args.config_file) as f:
            feeds = json.load(f)
    except FileNotFoundError:
        print(f"Error: Config file not found: {args.config_file}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in config file: {e}", file=sys.stderr)
        sys.exit(1)

    # Create client with cookie persistence
    with httpx.Client(follow_redirects=True) as client:
        # Login
        print(f"Logging in to {server_url}...")
        login_response = client.post(
            f"{server_url}/auth/login",
            data={"username": args.username, "password": args.password, "next": "/"},
        )

        if login_response.status_code != 200:
            print(
                f"Error: Login failed (status {login_response.status_code})",
                file=sys.stderr,
            )
            sys.exit(1)

        # Check if we got a session cookie
        if "session" not in client.cookies:
            print("Error: Login failed - no session cookie received", file=sys.stderr)
            sys.exit(1)

        print("Login successful")

        # Upload config
        print("Uploading config...")
        config_response = client.post(
            f"{server_url}/config",
            data={
                "feeds_json": json.dumps(feeds, indent=2),
                "cache_media": "false",
                "default_cooldown_minutes": "15",
                "base_url": server_url,
            },
        )

        if config_response.status_code == 200:
            print("Config uploaded successfully")
        else:
            print(
                f"Error: Config upload failed (status {config_response.status_code})",
                file=sys.stderr,
            )
            print(config_response.text[:500], file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
