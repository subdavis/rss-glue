import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol


class SimpleCache(Protocol):
    def get(self, key: str, namespace: str) -> Optional[dict]:
        pass

    def set(self, key: str, value: dict, namespace: str) -> None:
        pass

    def delete(self, key: str, namespace: str) -> None:
        pass

    def keys(
        self,
        namespace: str,
        limit: int = 50,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[str]:
        pass


class FileCache:
    def __init__(self, root: Path):
        self.root = root

    def _ensure_namespace(self, namespace: str) -> Path:
        parent = self.root / namespace.replace(os.sep, "_")
        parent.mkdir(parents=True, exist_ok=True)
        return parent

    def getPath(self, key: str, ext: str, namespace: str) -> Path:
        pathsafe_key = key.replace(os.sep, "_")
        return self._ensure_namespace(namespace) / f"{pathsafe_key}.{ext}"

    def getRelativePath(self, key: str, ext: str, namespace: str) -> Path:
        pathsafe_key = key.replace(os.sep, "_")
        relpath = Path(namespace.replace(os.sep, "_")) / f"{pathsafe_key}.{ext}"
        return relpath

    def write(self, key: str, ext: str, data: str, namespace: str) -> Path:
        with open(self.getPath(key, ext, namespace), "w") as f:
            f.write(data)
        return self.getRelativePath(key, ext, namespace)


class MediaCache:
    def __init__(self, root: Path):
        self.root = root

    def _ensure_media_dir(self, media_type: str, prefix: str) -> Path:
        """Ensure the media directory exists for the given type and hash prefix."""
        parent = self.root / media_type / prefix
        parent.mkdir(parents=True, exist_ok=True)
        return parent

    def getPath(self, filename: str, media_type: str) -> Path:
        """Get the absolute path for a media file.

        Args:
            filename: The full filename including extension (e.g., '12349rasdfo8q4.jpg')
            media_type: Either 'images' or 'videos'

        Returns:
            Absolute Path to the media file
        """
        prefix = filename[:2]
        return self._ensure_media_dir(media_type, prefix) / filename

    def getRelativePath(self, filename: str, media_type: str) -> Path:
        """Get the relative path for a media file.

        Args:
            filename: The full filename including extension (e.g., '12349rasdfo8q4.jpg')
            media_type: Either 'images' or 'videos'

        Returns:
            Relative Path to the media file
        """
        prefix = filename[:2]
        return Path(media_type) / prefix / filename


class JsonCache(SimpleCache):
    def __init__(self, root: Path):
        self.root = root

    def _ensure_namespace(self, namespace: str) -> Path:
        parent = self.root / namespace.replace(os.sep, "_")
        parent.mkdir(parents=True, exist_ok=True)
        return parent

    def cacheFile(self, key: str, namespace: str) -> Path:
        pathsafe_key = key.replace(os.sep, "_")
        return self._ensure_namespace(namespace) / f"{pathsafe_key}.json"

    def get(self, key: str, namespace: str) -> Optional[dict]:
        if not self.cacheFile(key, namespace).exists():
            return None
        with open(self.cacheFile(key, namespace)) as f:
            return json.load(f)

    def set(self, key: str, value: dict, namespace: str) -> None:
        with open(self.cacheFile(key, namespace), "w") as f:
            json.dump(value, f, indent=2)

        # Set mtime to posted_time if available (for proper chronological sorting)
        if "posted_time" in value:
            posted_time_str = value["posted_time"]
            posted_dt = datetime.fromisoformat(posted_time_str)
            # Convert to timestamp (handles timezone-aware datetimes correctly)
            mtime = posted_dt.timestamp()
            os.utime(self.cacheFile(key, namespace), (mtime, mtime))
        # Otherwise, filesystem will use current time automatically

    def delete(self, key: str, namespace: str) -> None:
        os.remove(self.cacheFile(key, namespace))

    def keys(
        self,
        namespace: str,
        limit: int = 50,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[str]:
        ns_path = self._ensure_namespace(namespace)

        # Collect files with their modification times
        files = []
        for entry in os.scandir(ns_path):
            if entry.name.endswith(".json") and entry.name != "meta.json":
                # DirEntry.stat() is cached from the directory scan
                mtime_timestamp = entry.stat().st_mtime

                # Apply start/end filters if provided
                if start is not None or end is not None:
                    # Use the timezone from start/end if they are timezone-aware
                    tz = None
                    if start is not None and start.tzinfo is not None:
                        tz = start.tzinfo
                    elif end is not None and end.tzinfo is not None:
                        tz = end.tzinfo

                    mtime = datetime.fromtimestamp(mtime_timestamp, tz=tz)
                    if start and mtime < start:
                        continue
                    if end and mtime >= end:
                        continue

                files.append((entry.name[:-5], mtime_timestamp))  # Remove .json extension

        # Sort reverse-chronologically (most recent first)
        files.sort(key=lambda x: x[1], reverse=True)

        if limit > 0:
            return [name for name, _ in files[:limit]]
        return [name for name, _ in files]
