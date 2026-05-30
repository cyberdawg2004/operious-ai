"""Typed Shopify enrichment value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ShopifyProductVariant:
    variant_id: str
    title: str
    sku: str
    inventory_quantity: int | None
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class ShopifyProduct:
    product_id: str
    title: str
    vendor: str
    product_type: str
    variants: tuple[ShopifyProductVariant, ...]
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class ShopifyOrder:
    order_id: str
    order_number: int
    created_at: str
    fulfillment_status: str | None
    line_item_skus: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShopifyEnrichmentResult:
    sku: str
    product: ShopifyProduct | None
    recent_orders: tuple[ShopifyOrder, ...]
    batch_hint: str | None
    enrichment_source: str


__all__ = [
    "ShopifyEnrichmentResult",
    "ShopifyOrder",
    "ShopifyProduct",
    "ShopifyProductVariant",
]
