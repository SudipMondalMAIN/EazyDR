"""
Storage Service abstraction.

RULE: business logic (routers/services in app/modules/*) must NEVER import
cloudinary/boto3/etc directly. They only ever call `storage_service.upload_file`
etc. Swapping Cloudinary -> S3 -> R2 later = write a new class implementing
StorageService and flip STORAGE_PROVIDER in .env. Zero changes anywhere else.
"""
from abc import ABC, abstractmethod
from typing import BinaryIO

from app.core.config import settings


class StorageService(ABC):
    @abstractmethod
    async def upload_file(self, file: BinaryIO, folder: str, public_id: str | None = None) -> str:
        """Uploads a file, returns a storage key/id (NOT necessarily the public URL)."""

    @abstractmethod
    async def delete_file(self, file_key: str) -> bool:
        ...

    @abstractmethod
    def get_public_url(self, file_key: str) -> str:
        ...


class CloudinaryStorageService(StorageService):
    def __init__(self):
        import cloudinary

        cloudinary.config(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key,
            api_secret=settings.cloudinary_api_secret,
            secure=True,
        )

    async def upload_file(self, file: BinaryIO, folder: str, public_id: str | None = None) -> str:
        import cloudinary.uploader

        result = cloudinary.uploader.upload(file, folder=folder, public_id=public_id)
        return result["public_id"]

    async def delete_file(self, file_key: str) -> bool:
        import cloudinary.uploader

        result = cloudinary.uploader.destroy(file_key)
        return result.get("result") == "ok"

    def get_public_url(self, file_key: str) -> str:
        import cloudinary.utils

        url, _ = cloudinary.utils.cloudinary_url(file_key, secure=True)
        return url


class LocalStorageService(StorageService):
    """Fallback used in dev/tests when no Cloudinary creds are set, so the
    app still boots and file upload endpoints don't 500 out of the box."""

    def __init__(self):
        import os

        self.base_dir = "local_storage"
        os.makedirs(self.base_dir, exist_ok=True)

    async def upload_file(self, file: BinaryIO, folder: str, public_id: str | None = None) -> str:
        import os
        import uuid

        os.makedirs(os.path.join(self.base_dir, folder), exist_ok=True)
        key = f"{folder}/{public_id or uuid.uuid4().hex}"
        with open(os.path.join(self.base_dir, key), "wb") as out:
            out.write(file.read())
        return key

    async def delete_file(self, file_key: str) -> bool:
        import os

        path = os.path.join(self.base_dir, file_key)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def get_public_url(self, file_key: str) -> str:
        return f"/static/{file_key}"


def get_storage_service() -> StorageService:
    if settings.storage_provider == "cloudinary" and settings.cloudinary_cloud_name:
        return CloudinaryStorageService()
    return LocalStorageService()


storage_service = get_storage_service()
