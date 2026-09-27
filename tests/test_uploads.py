from io import BytesIO
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image

from app.core.config import settings
from tests.conftest import UserFactory, auth_header

pytestmark = pytest.mark.anyio


def make_image(fmt: str = "PNG", size: tuple[int, int] = (64, 48), mode: str = "RGB") -> bytes:
    buffer = BytesIO()
    Image.new(mode, size, "orange").save(buffer, fmt)
    return buffer.getvalue()


async def upload(client: AsyncClient, headers: dict, data: bytes, folder: str = "foods"):
    return await client.post(
        "/uploads/images",
        headers=headers,
        data={"folder": folder},
        files={"file": ("photo.png", data, "image/png")},
    )


@pytest.mark.parametrize(("fmt", "mode"), [("PNG", "RGBA"), ("JPEG", "RGB"), ("GIF", "P")])
async def test_upload_converts_to_webp(
    client: AsyncClient, make_user: UserFactory, fmt: str, mode: str
) -> None:
    user = await make_user()

    response = await upload(client, auth_header(user), make_image(fmt, mode=mode))

    assert response.status_code == 201
    body = response.json()
    assert body["key"].startswith("foods/") and body["key"].endswith(".webp")
    assert body["url"] == f"/media/{body['key']}"
    with Image.open(Path(settings.local_upload_dir) / body["key"]) as stored:
        assert stored.format == "WEBP"


async def test_large_images_are_scaled_down(client: AsyncClient, make_user: UserFactory) -> None:
    user = await make_user()

    response = await upload(client, auth_header(user), make_image(size=(3200, 1000)))

    with Image.open(Path(settings.local_upload_dir) / response.json()["key"]) as stored:
        assert stored.size == (1600, 500)


async def test_rejects_files_that_are_not_images(
    client: AsyncClient, make_user: UserFactory
) -> None:
    user = await make_user()

    response = await upload(client, auth_header(user), b"<?php echo 'hi'; ?>")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_image"


async def test_rejects_unsupported_formats(client: AsyncClient, make_user: UserFactory) -> None:
    user = await make_user()

    response = await upload(client, auth_header(user), make_image("BMP"))

    assert response.json()["code"] == "unsupported_image"


async def test_rejects_big_files(
    client: AsyncClient, make_user: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await make_user()
    monkeypatch.setattr(settings, "max_upload_mb", 0)

    response = await upload(client, auth_header(user), make_image())

    assert response.status_code == 413


async def test_unknown_folder(client: AsyncClient, make_user: UserFactory) -> None:
    user = await make_user()

    response = await upload(client, auth_header(user), make_image(), folder="../etc")

    assert response.status_code == 422


async def test_upload_needs_login(client: AsyncClient) -> None:
    response = await upload(client, {}, make_image())

    assert response.status_code == 401
