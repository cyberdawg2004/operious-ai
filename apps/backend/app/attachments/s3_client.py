"""Thin boto3-backed S3 client for attachment ciphertext.

First concrete S3 implementation in this codebase — the
``SesRawEmailFetcher`` protocol in ``app.boundary.adapters.email_ses``
anticipated S3-backed fetching but was never implemented. boto3 is a new
dependency, scoped to this module only.

This class only ever sees/stores CIPHERTEXT. The security boundary is the
app-layer envelope encryption applied by the caller (see
``app.attachments.storage_service``) before bytes reach ``put()`` — SSE-S3
here is defense-in-depth, not the boundary. No AWS KMS is used or required.
"""

from __future__ import annotations

import boto3
from botocore.config import Config as BotoConfig

from app.core.config import Settings


class AttachmentBlobStore:
    """Private, tenant-scoped object storage for attachment ciphertext.

    boto3 is synchronous; callers from async code MUST wrap calls with
    ``asyncio.to_thread`` (see ``app.attachments.storage_service`` and
    ``app.attachments.repository``) — this class does no async work itself
    so it stays trivially unit-testable against a fake/mocked client.
    """

    __slots__ = ("_client", "_bucket")

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=BotoConfig(retries={"max_attempts": 3, "mode": "standard"}),
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "AttachmentBlobStore":
        return cls(
            bucket=settings.ATTACHMENTS_S3_BUCKET,
            region=settings.ATTACHMENTS_S3_REGION,
            access_key_id=settings.ATTACHMENTS_S3_ACCESS_KEY_ID,
            secret_access_key=settings.ATTACHMENTS_S3_SECRET_ACCESS_KEY,
        )

    def put(self, key: str, ciphertext: bytes) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=ciphertext,
            ServerSideEncryption="AES256",
        )

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)
