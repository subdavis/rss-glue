"""Standalone background worker entry point.

Run this to execute only the background worker without the web server.
Useful for running the worker as a separate service or on a schedule.
"""

import asyncio
import logging
import signal
import sys

from rss_glue.database import create_db_and_tables
from rss_glue.services.background_worker import background_worker_loop

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("rss_glue.worker")


async def main():
    """Run the standalone worker."""
    logger.info("Starting standalone RSS Glue background worker...")

    # Initialize database and run migrations
    create_db_and_tables()

    # Create shutdown event
    shutdown_event = asyncio.Event()

    # Handle shutdown signals
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run worker loop
    try:
        await background_worker_loop(shutdown_event)
    except Exception as e:
        logger.error(f"Worker failed with error: {e}", exc_info=True)
        return 1

    logger.info("Worker shut down successfully")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
