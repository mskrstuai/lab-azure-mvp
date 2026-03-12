"""
Image rendering utilities for displaying product images in Jupyter notebooks.
"""

import base64
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.credentials import AzureNamedKeyCredential
from datetime import datetime, timedelta, timezone
from IPython.display import HTML, display

from ..settings.azure_storage_settings import AzureStorageImagesSettings

logger = logging.getLogger(__name__)


class ImageRenderer:
    """
    Renders product images from Azure Blob Storage in Jupyter notebooks.
    """

    _credential: Optional[DefaultAzureCredential] = None
    _blob_service_client: Optional[BlobServiceClient] = None
    _user_delegation_key = None
    _user_delegation_key_expiry: Optional[datetime] = None

    def __init__(self, settings: Optional[AzureStorageImagesSettings] = None):
        self.settings = settings or AzureStorageImagesSettings()
        self._image_exists_cache: Dict[str, bool] = {}

        has_local = bool(getattr(self.settings, "effective_local_images_path", None))
        if has_local or self.settings.sas_token:
            return
        if ImageRenderer._blob_service_client is None:
            ImageRenderer._blob_service_client = self._create_blob_client()

    def _create_blob_client(self) -> BlobServiceClient:
        conn_str = getattr(self.settings, "effective_connection_string", None)
        if conn_str:
            return BlobServiceClient.from_connection_string(conn_str)
        acct_key = getattr(self.settings, "effective_account_key", None)
        if acct_key:
            return BlobServiceClient(
                account_url=self.settings.account_url,
                credential=AzureNamedKeyCredential(self.settings.account_name, acct_key),
            )
        if ImageRenderer._credential is None:
            ImageRenderer._credential = DefaultAzureCredential()
        return BlobServiceClient(
            account_url=self.settings.account_url,
            credential=ImageRenderer._credential,
        )

    @classmethod
    def _get_user_delegation_key(cls, settings: AzureStorageImagesSettings):
        if cls._blob_service_client is None:
            raise RuntimeError("Blob client not initialized")
        now = datetime.now(timezone.utc)
        if (
            cls._user_delegation_key is None
            or cls._user_delegation_key_expiry is None
            or cls._user_delegation_key_expiry < now + timedelta(minutes=5)
        ):
            key_start = now
            key_expiry = now + timedelta(hours=1)
            cls._user_delegation_key = cls._blob_service_client.get_user_delegation_key(
                key_start_time=key_start, key_expiry_time=key_expiry
            )
            cls._user_delegation_key_expiry = key_expiry
        return cls._user_delegation_key

    def _get_local_image_path(self, article_id: str) -> Optional[Path]:
        local_base = getattr(self.settings, "effective_local_images_path", None)
        if not local_base:
            return None
        blob_path = self._get_blob_path(article_id)
        local_path = Path(local_base) / blob_path
        return local_path if local_path.exists() else None

    def _get_data_url_from_file(self, path: Path) -> str:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"

    def _get_blob_path(self, article_id: str) -> str:
        article_id_padded = str(article_id).zfill(10)
        prefix = article_id_padded[:3]
        return f"images/{prefix}/{article_id_padded}.jpg"

    def get_image_url(self, article_id: Union[str, int]) -> str:
        article_id_str = str(article_id)
        blob_path = self._get_blob_path(article_id_str)

        local_path = self._get_local_image_path(article_id_str)
        if local_path:
            return self._get_data_url_from_file(local_path)

        if self.settings.sas_token:
            base_url = f"{self.settings.container_url}/{blob_path}"
            token = self.settings.sas_token.lstrip("?")
            return f"{base_url}?{token}"

        if ImageRenderer._blob_service_client is None:
            return f"{self.settings.container_url}/{blob_path}"
        try:
            user_delegation_key = self._get_user_delegation_key(self.settings)
            sas_token = generate_blob_sas(
                account_name=self.settings.account_name,
                container_name=self.settings.container_name,
                blob_name=blob_path,
                user_delegation_key=user_delegation_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            return f"{self.settings.container_url}/{blob_path}?{sas_token}"
        except Exception as e:
            logger.warning(f"Failed to generate SAS for {article_id}: {e}")
            return f"{self.settings.container_url}/{blob_path}"

    def image_exists(self, article_id: Union[str, int]) -> bool:
        article_id_str = str(article_id)

        if self._get_local_image_path(article_id_str):
            return True

        if ImageRenderer._blob_service_client is None:
            return False

        if article_id_str in self._image_exists_cache:
            return self._image_exists_cache[article_id_str]

        try:
            blob_path = self._get_blob_path(article_id_str)
            container_client = ImageRenderer._blob_service_client.get_container_client(
                self.settings.container_name
            )
            exists = container_client.get_blob_client(blob_path).exists()
            self._image_exists_cache[article_id_str] = exists
            return exists
        except Exception as e:
            logger.debug(f"Error checking image existence for {article_id_str}: {e}")
            self._image_exists_cache[article_id_str] = False
            return False

    def filter_products_with_images(self, products: List[Any]) -> List[Any]:
        filtered = []
        for product in products:
            article_id = self._extract_article_id(product)
            if article_id and self.image_exists(article_id):
                filtered.append(product)
        return filtered

    def _extract_article_id(self, product: Any) -> Optional[str]:
        if product is None:
            return None

        if isinstance(product, dict):
            for field in ["Id", "article_id", "ArticleId", "id"]:
                if field in product:
                    return str(product[field])
            if "document" in product:
                return self._extract_article_id(product["document"])
            return None

        for attr in ["article_id", "Id", "id", "ArticleId"]:
            if hasattr(product, attr):
                value = getattr(product, attr)
                if value is not None:
                    return str(value)

        if hasattr(product, "document"):
            return self._extract_article_id(product.document)

        return None

    def _extract_field(
        self, product: Any, field_names: List[str], default: str = ""
    ) -> str:
        if product is None:
            return default

        if isinstance(product, dict):
            for field in field_names:
                if field in product and product[field]:
                    return str(product[field])
            if "document" in product:
                return self._extract_field(product["document"], field_names, default)
            return default

        for attr in field_names:
            if hasattr(product, attr):
                value = getattr(product, attr)
                if value is not None:
                    return str(value)

        if hasattr(product, "document"):
            return self._extract_field(product.document, field_names, default)

        return default

    def _product_card_html(
        self, product: Any, width: int = 150, show_details: bool = True
    ) -> str:
        article_id = self._extract_article_id(product)
        if not article_id:
            return "<div style='padding: 10px; color: #999;'>No image</div>"

        image_url = self.get_image_url(article_id)

        name = self._extract_field(
            product, ["ProductName", "prod_name", "name", "Name"]
        )
        color = self._extract_field(
            product, ["ColourGroupName", "colour_group_name", "color", "Color"]
        )
        product_type = self._extract_field(
            product,
            ["ProductTypeName", "product_type_name", "product_type", "ProductType"],
        )

        html = f"""
        <div style="
            display: inline-block;
            text-align: center;
            padding: 10px;
            margin: 5px;
            border: 1px solid #eee;
            border-radius: 8px;
            background: #fff;
            vertical-align: top;
            width: {width + 20}px;
        ">
            <img 
                src="{image_url}" 
                alt="{name}"
                style="
                    width: {width}px;
                    height: {int(width * 1.3)}px;
                    object-fit: cover;
                    border-radius: 4px;
                "
                onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"
            />
            <div style="
                display: none;
                width: {width}px;
                height: {int(width * 1.3)}px;
                background: #f5f5f5;
                border-radius: 4px;
                align-items: center;
                justify-content: center;
                color: #999;
                font-size: 12px;
            ">No image</div>
        """

        if show_details:
            html += f"""
            <div style="margin-top: 8px; font-size: 12px; line-height: 1.4;">
                <div style="
                    font-weight: 600;
                    color: #333;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    max-width: {width}px;
                " title="{name}">{name or 'Unknown'}</div>
                <div style="color: #666;">{product_type}</div>
                <div style="color: #888;">{color}</div>
                <div style="color: #aaa; font-size: 10px;">ID: {article_id}</div>
            </div>
            """

        html += "</div>"
        return html

    def display_product(
        self, product: Any, width: int = 200, show_details: bool = True
    ) -> None:
        html = self._product_card_html(product, width, show_details)
        display(HTML(html))

    def display_products(
        self,
        products: List[Any],
        columns: int = 4,
        image_width: int = 150,
        show_details: bool = True,
        title: Optional[str] = None,
        skip_missing_images: bool = False,
    ) -> None:
        if not products:
            display(HTML("<p style='color: #999;'>No products to display</p>"))
            return

        if skip_missing_images:
            products = self.filter_products_with_images(products)
            if not products:
                display(
                    HTML(
                        "<p style='color: #999;'>No products with images to display</p>"
                    )
                )
                return

        html_parts = []

        if title:
            html_parts.append(
                f"""
                <h3 style="margin: 10px 0; color: #333;">{title}</h3>
            """
            )

        html_parts.append(
            f"""
            <div style="
                display: grid;
                grid-template-columns: repeat({columns}, 1fr);
                gap: 10px;
                padding: 10px;
                background: #fafafa;
                border-radius: 8px;
            ">
        """
        )

        for product in products:
            html_parts.append(
                self._product_card_html(product, image_width, show_details)
            )

        html_parts.append("</div>")

        display(HTML("".join(html_parts)))

    def display_search_results(
        self,
        search_response: Any,
        columns: int = 4,
        image_width: int = 150,
        title: Optional[str] = None,
        skip_missing_images: bool = False,
    ) -> None:
        if hasattr(search_response, "results"):
            products = search_response.results
        elif hasattr(search_response, "products"):
            products = search_response.products
        elif isinstance(search_response, list):
            products = search_response
        else:
            products = []

        if skip_missing_images and products:
            products = self.filter_products_with_images(products)

        if title is None:
            count = len(products) if products else 0
            title = f"Search Results ({count} items)"

        self.display_products(
            products,
            columns=columns,
            image_width=image_width,
            show_details=True,
            title=title,
            skip_missing_images=False,
        )


def display_product_images(
    products: List[Any],
    columns: int = 4,
    image_width: int = 150,
    title: Optional[str] = None,
) -> None:
    renderer = ImageRenderer()
    renderer.display_products(products, columns, image_width, title=title)
