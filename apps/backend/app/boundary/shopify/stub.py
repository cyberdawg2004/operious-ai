"""Deterministic Shopify enrichment stub."""

from __future__ import annotations

from app.boundary.shopify.models import ShopifyOrder, ShopifyProduct, ShopifyProductVariant


class DeterministicStubShopifyClient:
    """Return deterministic fixture data when live Shopify credentials are absent."""

    async def get_product_by_sku(
        self,
        sku: str,
    ) -> ShopifyProduct:
        return ShopifyProduct(
            product_id=f"stub-{sku[:8]}",
            title=f"Stub Product ({sku})",
            vendor="Anker",
            product_type="Electronics",
            variants=(
                ShopifyProductVariant(
                    variant_id=f"var-{sku[:6]}",
                    title="Default",
                    sku=sku,
                    inventory_quantity=1000,
                    created_at=None,
                    updated_at=None,
                ),
            ),
            created_at=None,
            updated_at=None,
        )

    async def get_recent_orders_by_sku(
        self,
        sku: str,
        limit: int = 10,
    ) -> list[ShopifyOrder]:
        del limit
        return [
            ShopifyOrder(
                order_id=f"stub-order-{sku[:6]}",
                order_number=12345,
                created_at="2026-01-01T00:00:00Z",
                fulfillment_status="fulfilled",
                line_item_skus=(sku,),
            )
        ]


__all__ = ["DeterministicStubShopifyClient"]
