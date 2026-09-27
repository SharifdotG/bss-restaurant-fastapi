from app.schemas.common import CamelModel


class UploadedImage(CamelModel):
    key: str
    url: str
