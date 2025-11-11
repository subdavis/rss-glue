import os
from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from rss_glue.cache import SimpleCache


class MongoCache(SimpleCache):
    """MongoDB implementation of the SimpleCache protocol.

    Stores cache entries in MongoDB collections organized by namespace.
    Each entry contains:
    - _id: the cache key
    - value: the cached data (dict)
    - updated_at: timestamp of last update
    """

    def __init__(self, connection_string: str, database_name: str = "rss_glue_cache"):
        """Initialize MongoDB cache.

        Args:
            connection_string: MongoDB connection string with authentication.
                Examples:
                - Local development: "mongodb://localhost:27017/"
                - With auth: "mongodb://username:password@localhost:27017/"
                - MongoDB Atlas: "mongodb+srv://username:password@cluster.mongodb.net/"
            database_name: Name of the database to use for caching

        Note:
            For security, avoid hardcoding credentials. Use environment variables:
            MONGO_CONNECTION_STRING="mongodb://user:pass@host:port/"
        """
        self.client: MongoClient = MongoClient(connection_string)
        self.db: Database = self.client[database_name]

    def _get_collection(self, namespace: str) -> Collection:
        """Get or create a collection for the given namespace.

        Args:
            namespace: Cache namespace (used as collection name)

        Returns:
            MongoDB collection for this namespace
        """
        # Sanitize namespace to be a valid MongoDB collection name
        collection_name = namespace.replace(os.sep, "_").replace(".", "_")
        collection = self.db[collection_name]

        # Ensure index on updated_at for efficient time-based queries
        collection.create_index([("updated_at", DESCENDING)])

        return collection

    def get(self, key: str, namespace: str) -> Optional[dict]:
        """Get a value from the cache.

        Args:
            key: Cache key
            namespace: Cache namespace

        Returns:
            Cached value dict or None if not found
        """
        collection = self._get_collection(namespace)
        doc = collection.find_one({"_id": key})

        if doc is None:
            return None

        # Return just the value, excluding MongoDB metadata
        return doc.get("value")

    def set(self, key: str, value: dict, namespace: str) -> None:
        """Set a value in the cache.

        Args:
            key: Cache key
            value: Value to cache (must be a dict)
            namespace: Cache namespace
        """
        collection = self._get_collection(namespace)

        doc = {
            "_id": key,
            "value": value,
            "updated_at": datetime.now(timezone.utc),
        }

        # Use replace_one with upsert to update existing or insert new
        collection.replace_one({"_id": key}, doc, upsert=True)

    def delete(self, key: str, namespace: str) -> None:
        """Delete a value from the cache.

        Args:
            key: Cache key
            namespace: Cache namespace
        """
        collection = self._get_collection(namespace)
        collection.delete_one({"_id": key})

    def keys(
        self,
        namespace: str,
        limit: int = 50,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[str]:
        """Get cache keys from a namespace, optionally filtered by time range.

        Args:
            namespace: Cache namespace
            limit: Maximum number of keys to return (default: 50)
            start: Optional start time filter (inclusive)
            end: Optional end time filter (inclusive)

        Returns:
            List of cache keys, sorted reverse-chronologically (most recent first)
        """
        collection = self._get_collection(namespace)

        # Build time range query
        query: dict[str, Any] = {}
        if start or end:
            query["updated_at"] = {}
            if start:
                query["updated_at"]["$gte"] = start
            if end:
                query["updated_at"]["$lte"] = end

        # Query with sort and limit
        cursor = (
            collection.find(query, {"_id": 1})  # Only return the _id field
            .sort("updated_at", DESCENDING)
            .limit(limit)
        )

        return [doc["_id"] for doc in cursor]

    def close(self) -> None:
        """Close the MongoDB connection."""
        self.client.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - closes connection."""
        self.close()
