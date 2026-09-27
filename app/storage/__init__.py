from functools import lru_cache

from app.core.config import settings
from app.storage.base import Storage


@lru_cache
def get_storage() -> Storage:
    if settings.storage_backend == "r2":
        from app.storage.r2 import R2Storage

        return R2Storage(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket=settings.r2_bucket,
            public_url=settings.r2_public_url,
        )

    from app.storage.local import LocalStorage

    return LocalStorage(settings.local_upload_dir)


def file_url(key: str | None) -> str | None:
    return get_storage().url(key) if key else None


__all__ = ["Storage", "file_url", "get_storage"]
