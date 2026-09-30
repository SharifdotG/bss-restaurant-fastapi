import logging
import re
from enum import StrEnum
from io import BytesIO
from uuid import uuid4

from anyio import to_thread
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.exceptions import BadRequestError
from app.storage import get_storage

logger = logging.getLogger(__name__)


class ImageFolder(StrEnum):
    FOODS = "foods"
    CATEGORIES = "categories"
    TABLES = "tables"
    USERS = "users"
    RECEIPTS = "receipts"


# MPO is what some phones produce for normal jpeg photos
ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP", "GIF"}
MAX_SIDE = 1600
MAX_PIXELS = 40_000_000

_key_pattern = re.compile(r"^([a-z]+)/[0-9a-f]{32}\.webp$")


def _to_webp(data: bytes) -> bytes:
    try:
        with Image.open(BytesIO(data)) as img:
            if img.format not in ALLOWED_FORMATS:
                raise BadRequestError(
                    "Unsupported image type, use JPEG, PNG, WEBP or GIF", code="unsupported_image"
                )
            if img.width * img.height > MAX_PIXELS:
                raise BadRequestError("Image dimensions are too large", code="image_too_large")

            # phones store rotation in exif, apply it before exif gets dropped
            image = ImageOps.exif_transpose(img)
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            if image.mode not in ("RGB", "RGBA"):
                has_alpha = image.mode in ("LA", "P") and "transparency" in image.info
                image = image.convert("RGBA" if has_alpha or image.mode == "LA" else "RGB")

            out = BytesIO()
            image.save(out, "WEBP", quality=82, method=4)
            return out.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        raise BadRequestError("The file is not a valid image", code="invalid_image") from None


async def save_image(data: bytes, folder: ImageFolder) -> str:
    webp = await to_thread.run_sync(_to_webp, data)
    key = f"{folder}/{uuid4().hex}.webp"
    await get_storage().save(key, webp, "image/webp")
    return key


def check_image_key(key: str, folder: ImageFolder) -> str:
    """Only accept keys that came out of our own upload endpoint for the right folder."""
    match = _key_pattern.match(key)
    if match is None or match.group(1) != folder:
        raise BadRequestError("Invalid image, upload it first", code="invalid_image_key")
    return key


async def delete_image(key: str | None) -> None:
    if not key:
        return
    try:
        await get_storage().delete(key)
    except Exception:
        # a leftover file is not worth failing the request over
        logger.warning("could not delete image %s", key, exc_info=True)
