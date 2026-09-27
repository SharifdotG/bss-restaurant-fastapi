from typing import Annotated

from fastapi import APIRouter, Form, UploadFile, status

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.exceptions import PayloadTooLargeError
from app.schemas.upload import UploadedImage
from app.services.images import ImageFolder, save_image
from app.storage import get_storage

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/images", response_model=UploadedImage, status_code=status.HTTP_201_CREATED)
async def upload_image(
    _: CurrentUser, file: UploadFile, folder: Annotated[ImageFolder, Form()]
) -> UploadedImage:
    """Upload first, then send the returned `key` as `imageKey` when creating or updating
    a food, category, table or profile. Images are resized and converted to webp."""
    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise PayloadTooLargeError(f"Images can be at most {settings.max_upload_mb} MB")

    key = await save_image(data, folder)
    return UploadedImage(key=key, url=get_storage().url(key))
