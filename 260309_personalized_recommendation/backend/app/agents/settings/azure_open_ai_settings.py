from semantic_kernel.kernel_pydantic import KernelBaseSettings
from typing import ClassVar


class AzureOpenAiSettings(KernelBaseSettings):
    env_prefix: ClassVar[str] = "AZURE_OPENAI_"

    endpoint: str
    chat_deployment_name: str
    text_embedding_deployment_name: str
    api_version: str = "2024-10-21"
    api_key: str
