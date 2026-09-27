import boto3
from anyio import to_thread
from botocore.config import Config


class R2Storage:
    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        public_url: str,
    ) -> None:
        self.bucket = bucket
        self.public_url = public_url.rstrip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            config=Config(retries={"max_attempts": 3, "mode": "standard"}),
        )

    # boto3 is blocking, so every call goes to a worker thread

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        await to_thread.run_sync(
            lambda: self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                # keys are random and never reused, browsers can cache forever
                CacheControl="public, max-age=31536000, immutable",
            )
        )

    async def delete(self, key: str) -> None:
        await to_thread.run_sync(lambda: self.client.delete_object(Bucket=self.bucket, Key=key))

    def url(self, key: str) -> str:
        return f"{self.public_url}/{key}"
