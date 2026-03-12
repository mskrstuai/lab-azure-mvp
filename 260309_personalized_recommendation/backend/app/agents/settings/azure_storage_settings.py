"""Azure Blob Storage settings for images and data."""

import os
from pathlib import Path
from typing import ClassVar, Optional

from semantic_kernel.kernel_pydantic import KernelBaseSettings


class AzureStorageImagesSettings(KernelBaseSettings):
    """Settings for the Azure Blob Storage account containing product images."""

    env_prefix: ClassVar[str] = "AZURE_STORAGE_IMAGES_"

    account_name: str = "conversational6519399928"
    container_name: str = "hm-images"

    connection_string: Optional[str] = None
    account_key: Optional[str] = None
    sas_token: Optional[str] = None
    local_images_path: Optional[str] = None

    @property
    def effective_local_images_path(self) -> Optional[Path]:
        """Path to local images folder if it exists."""
        if self.local_images_path:
            local_path = Path(self.local_images_path)
            if (local_path / "images").exists():
                return local_path
        return None

    @property
    def effective_connection_string(self) -> Optional[str]:
        return self.connection_string or os.getenv("AZURE_STORAGE_CONNECTION_STRING")

    @property
    def effective_account_key(self) -> Optional[str]:
        return self.account_key or os.getenv("AZURE_STORAGE_ACCOUNT_KEY")

    @property
    def account_url(self) -> str:
        return f"https://{self.account_name}.blob.core.windows.net"

    @property
    def container_url(self) -> str:
        return f"{self.account_url}/{self.container_name}"

    def get_image_url(self, article_id: str, include_sas: bool = True) -> str:
        article_id_padded = str(article_id).zfill(10)
        prefix = article_id_padded[:3]
        base_url = f"{self.container_url}/images/{prefix}/{article_id_padded}.jpg"

        if include_sas and self.sas_token:
            token = self.sas_token.lstrip('?')
            return f"{base_url}?{token}"

        return base_url


class AzureStorageDataSettings(KernelBaseSettings):
    """Settings for the Azure Blob Storage account containing project data."""

    env_prefix: ClassVar[str] = "AZURE_STORAGE_DATA_"

    account_name: str = "code-391ff5ac-6576-460f-ba4d-7e03433c68b6"

    @property
    def account_url(self) -> str:
        return f"https://{self.account_name}.blob.core.windows.net"
