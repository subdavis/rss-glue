import json
import os
from pathlib import Path
from typing import Any, Optional, Protocol


class SimpleCache(Protocol):
    def get(self, key: str, namespace: str) -> Optional[dict]:
        pass

    def set(self, key: str, value: dict, namespace: str) -> None:
        pass

    def delete(self, key: str, namespace: str) -> None:
        pass

    def keys(self, namespace: str) -> list[str]:
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

    def nsFiles(self, ext: str, namespace: str) -> list[Path]:
        return list(self._ensure_namespace(namespace).glob(f"*.{ext}"))


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

    def delete(self, key: str, namespace: str) -> None:
        os.remove(self.cacheFile(key, namespace))

    def keys(self, namespace: str) -> list[str]:
        all_keys = [f.stem for f in self._ensure_namespace(namespace).glob("*.json")]
        return [key for key in all_keys if key != "meta"]
