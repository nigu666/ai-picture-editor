"""S3 兼容对象存储；实例显式绑定配置，不自动处理数据库素材记录。"""

import asyncio

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import Settings


class ObjectStorage:
    def __init__(self, settings: Settings):
        if not settings.s3_access_key or not settings.s3_secret_key:
            raise ValueError("对象存储访问配置尚未提供")
        self.settings = settings
        self._clients = {}

    def _client(self, endpoint: str | None = None):
        endpoint = endpoint or self.settings.s3_endpoint
        if endpoint not in self._clients:
            self._clients[endpoint] = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=self.settings.s3_access_key,
                aws_secret_access_key=self.settings.s3_secret_key,
                region_name="us-east-1",
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    connect_timeout=5,
                    read_timeout=10,
                    retries={"max_attempts": 2, "mode": "standard"},
                ),
            )
        return self._clients[endpoint]

    def _ensure_bucket(self) -> None:
        client = self._client()
        try:
            client.head_bucket(Bucket=self.settings.s3_bucket)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            client.create_bucket(Bucket=self.settings.s3_bucket)

    async def ensure_bucket(self) -> None:
        await asyncio.to_thread(self._ensure_bucket)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        client = self._client()
        await asyncio.to_thread(
            client.put_object,
            Bucket=self.settings.s3_bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    def _read(self, key: str) -> bytes:
        response = self._client().get_object(Bucket=self.settings.s3_bucket, Key=key)
        try:
            return response["Body"].read()
        finally:
            response["Body"].close()

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._read, key)

    async def delete(self, key: str) -> None:
        client = self._client()
        await asyncio.to_thread(client.delete_object, Bucket=self.settings.s3_bucket, Key=key)

    def signed_url(self, key: str) -> str:
        client = self._client(self.settings.s3_public_endpoint or None)
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.settings.s3_bucket, "Key": key},
            ExpiresIn=self.settings.s3_url_ttl,
        )

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients.clear()
