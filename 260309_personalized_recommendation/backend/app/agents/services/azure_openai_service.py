from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from azure.identity import DefaultAzureCredential

from ..settings.application_settings import ApplicationSettings
import logging

logger = logging.getLogger(__name__)


class AzureOpenAiSingleton:
    _instance = None

    @classmethod
    def get_client(cls) -> AzureChatCompletion:
        if cls._instance is None:
            token_endpoint: str = "https://cognitiveservices.azure.com/.default"
            app_settings = ApplicationSettings()
            logger.info(
                f"Creating AzureOpenAiSingleton instance with settings: {app_settings.model_dump(mode='json')}"
            )
            credentials = DefaultAzureCredential(
                exclude_managed_identity_credential=app_settings.skip_managed_identity_auth,
            )
            cls._instance = AzureChatCompletion(
                ad_token_provider=lambda: credentials.get_token(token_endpoint).token
            )

        return cls._instance
