from typing import ClassVar

from semantic_kernel.kernel_pydantic import KernelBaseSettings


class ApplicationSettings(KernelBaseSettings):
    env_prefix: ClassVar[str] = "APPLICATION_SETTINGS_"

    skip_managed_identity_auth: bool = False
    azure_tenant_id: str = ""
    azure_client_id: str = ""
