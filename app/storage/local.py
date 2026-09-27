from pathlib import Path

from anyio import to_thread


class LocalStorage:
    """Stores files on disk. Only meant for local development and tests."""

    def __init__(self, root: str, base_url: str = "/media") -> None:
        self.root = Path(root).resolve()
        self.base_url = base_url.rstrip("/")

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"invalid storage key: {key}")
        return path

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await to_thread.run_sync(write)

    async def delete(self, key: str) -> None:
        await to_thread.run_sync(lambda: self._path(key).unlink(missing_ok=True))

    def url(self, key: str) -> str:
        return f"{self.base_url}/{key}"
