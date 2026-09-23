"""Raw race-result files in an S3-compatible bucket (a Railway Bucket).

Keeping the original upload lets an admin download it again, and lets a
round be re-parsed after a parser fix without anyone digging the file up
from a game server. Storage is optional: without S3 settings (local
development, tests) imports still work and simply keep no copy.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.config import settings

logger = logging.getLogger(__name__)


class StorageUnavailable(RuntimeError):
    """Raised when a stored file is requested but no bucket is configured."""


def is_enabled() -> bool:
    return bool(settings.s3_bucket and settings.s3_access_key_id and settings.s3_secret_access_key)


@lru_cache(maxsize=1)
def _client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        region_name=settings.s3_region or None,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        # Railway Buckets need virtual-hosted URLs; a local MinIO needs "path".
        config=Config(s3={"addressing_style": settings.s3_addressing_style}),
    )


async def put(key: str, data: bytes, content_type: str) -> bool:
    """Store *data* under *key*. Returns False when storage is disabled."""
    if not is_enabled():
        logger.warning("S3 storage is not configured; %s was not kept", key)
        return False
    await asyncio.to_thread(
        _client().put_object,
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return True


async def get(key: str) -> bytes:
    if not is_enabled():
        raise StorageUnavailable("S3 storage is not configured")

    def _read() -> bytes:
        response = _client().get_object(Bucket=settings.s3_bucket, Key=key)
        return response["Body"].read()

    return await asyncio.to_thread(_read)


async def delete(key: str) -> None:
    if not is_enabled():
        return
    await asyncio.to_thread(_client().delete_object, Bucket=settings.s3_bucket, Key=key)
