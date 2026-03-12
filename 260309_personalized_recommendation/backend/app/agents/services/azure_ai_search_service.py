from __future__ import annotations

from typing import Dict

import logging
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient

from ..settings.application_settings import ApplicationSettings
from ..settings.azure_ai_search_settings import AzureSearchSettings

logger = logging.getLogger(__name__)


class AzureAiSearchSingleton:
    _clients: Dict[str, SearchClient] = {}

    token_endpoint: str = "https://cognitiveservices.azure.com/.default"

    @classmethod
    def get_client(cls, index_name: str = None) -> SearchClient:
        ai_search_settings = AzureSearchSettings()
        app_settings = ApplicationSettings()

        if index_name is None:
            raise ValueError("index_name must be provided to get_client method.")

        if index_name not in cls._clients:
            try:
                api_key = ai_search_settings.api_key or ai_search_settings.key
                if api_key:
                    credential = AzureKeyCredential(api_key)
                else:
                    credential = DefaultAzureCredential(
                        exclude_managed_identity_credential=app_settings.skip_managed_identity_auth
                    )
                cls._clients[index_name] = SearchClient(
                    endpoint=ai_search_settings.endpoint,
                    index_name=index_name,
                    credential=credential,
                )
            except Exception as se:
                logger.error(f"Error creating Azure AI Search client: {str(se)}")
                raise se
        return cls._clients[index_name]

    @classmethod
    def close_client(cls, index_name: str = None) -> None:
        if index_name is None:
            cls.close_all()
        elif index_name in cls._clients:
            cls._clients[index_name].close()
            del cls._clients[index_name]

    @classmethod
    async def close_all(cls) -> None:
        for client in cls._clients.values():
            client.close()
        cls._clients.clear()
