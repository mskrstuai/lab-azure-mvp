import logging

from semantic_kernel import Kernel

from ..services.azure_openai_service import AzureOpenAiSingleton

logger = logging.getLogger(__name__)


def setup_kernel() -> Kernel:
    kernel = Kernel()
    kernel.add_service(
        AzureOpenAiSingleton.get_client(),
    )
    return kernel
