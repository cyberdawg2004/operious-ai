"""Read-only Shopify Admin REST API client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from app.boundary.shopify.models import (
    ShopifyOrder,
    ShopifyProduct,
    ShopifyProductVariant,
)
from app.core.http import get_shared_http_client

JsonMapping = Mapping[str, object]


class ShopifyAPIClient:
    """Read-only Shopify Admin REST API client. Only GET requests are issued."""

    API_VERSION = "2024-01"

    def __init__(
        self,
        *,
        shop_domain: str,
        access_token: str,
    ) -> None:
        self._shop_domain = _normalise_domain(shop_domain)
        self._access_token = access_token.strip()

    async def get_product_by_sku(
        self,
        sku: str,
    ) -> ShopifyProduct | None:
        """Return the first product containing a matching variant SKU."""

        try:
            client = get_shared_http_client()
            response = await client.get(
                self._url("/products.json"),
                params={"limit": 250},
                headers=self._headers(),
                timeout=10.0,
            )
            if not 200 <= response.status_code < 300:
                return None
            payload = _json_mapping(response.json())
        except Exception:  # noqa: BLE001 - fail open.
            return None

        products = _json_mapping_list(payload.get("products"))
        target_sku = sku.strip()
        for product in products:
            variants = _variants(product)
            if any(variant.sku == target_sku for variant in variants):
                return _product(product, variants=variants)
        return None

    async def get_recent_orders_by_sku(
        self,
        sku: str,
        limit: int = 10,
    ) -> list[ShopifyOrder]:
        """Return recent orders whose line items contain the target SKU."""

        bounded_limit = max(1, min(limit, 250))
        try:
            client = get_shared_http_client()
            response = await client.get(
                self._url("/orders.json"),
                params={
                    "status": "any",
                    "limit": bounded_limit,
                },
                headers=self._headers(),
                timeout=10.0,
            )
            if not 200 <= response.status_code < 300:
                return []
            payload = _json_mapping(response.json())
        except Exception:  # noqa: BLE001 - fail open.
            return []

        orders = _json_mapping_list(payload.get("orders"))
        target_sku = sku.strip()
        results: list[ShopifyOrder] = []
        for order in orders:
            parsed = _order(order)
            if target_sku in parsed.line_item_skus:
                results.append(parsed)
        return results

    def _headers(self) -> dict[str, str]:
        return {
            "X-Shopify-Access-Token": self._access_token,
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        return (
            f"https://{self._shop_domain}/admin/api/"
            f"{self.API_VERSION}{path}"
        )


def _normalise_domain(shop_domain: str) -> str:
    domain = shop_domain.strip()
    domain = domain.removeprefix("https://").removeprefix("http://")
    return domain.strip("/")


def _json_mapping(value: object) -> JsonMapping:
    return cast(JsonMapping, value) if isinstance(value, Mapping) else {}


def _json_mapping_list(value: object) -> list[JsonMapping]:
    if not isinstance(value, list):
        return []
    mappings: list[JsonMapping] = []
    for item in cast(list[object], value):
        if isinstance(item, Mapping):
            mappings.append(cast(JsonMapping, item))
    return mappings


def _product(
    raw: JsonMapping,
    *,
    variants: tuple[ShopifyProductVariant, ...],
) -> ShopifyProduct:
    return ShopifyProduct(
        product_id=str(raw.get("id") or ""),
        title=str(raw.get("title") or ""),
        vendor=str(raw.get("vendor") or ""),
        product_type=str(raw.get("product_type") or ""),
        variants=variants,
        created_at=_optional_str(raw.get("created_at")),
        updated_at=_optional_str(raw.get("updated_at")),
    )


def _variants(raw_product: JsonMapping) -> tuple[ShopifyProductVariant, ...]:
    raw_variants = raw_product.get("variants")
    variant_rows = _json_mapping_list(raw_variants)
    variants: list[ShopifyProductVariant] = []
    for raw in variant_rows:
        variants.append(
            ShopifyProductVariant(
                variant_id=str(raw.get("id") or ""),
                title=str(raw.get("title") or ""),
                sku=str(raw.get("sku") or ""),
                inventory_quantity=_optional_int(raw.get("inventory_quantity")),
                created_at=_optional_str(raw.get("created_at")),
                updated_at=_optional_str(raw.get("updated_at")),
            )
        )
    return tuple(variants)


def _order(raw: JsonMapping) -> ShopifyOrder:
    return ShopifyOrder(
        order_id=str(raw.get("id") or ""),
        order_number=_optional_int(raw.get("order_number")) or 0,
        created_at=str(raw.get("created_at") or ""),
        fulfillment_status=_optional_str(raw.get("fulfillment_status")),
        line_item_skus=_line_item_skus(raw.get("line_items")),
    )


def _line_item_skus(raw_line_items: object) -> tuple[str, ...]:
    line_items = _json_mapping_list(raw_line_items)
    skus: list[str] = []
    for item in line_items:
        sku = item.get("sku")
        if isinstance(sku, str) and sku:
            skus.append(sku)
    return tuple(skus)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


__all__ = ["ShopifyAPIClient"]
