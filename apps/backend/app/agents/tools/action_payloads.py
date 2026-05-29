"""Typed payloads for governed action tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WarrantyClaimPayload(BaseModel):
    order_id: str = Field(min_length=1)
    product_sku: str = Field(min_length=1)
    issue_category: str = Field(min_length=1)
    customer_description: str = Field(min_length=1)

    model_config = ConfigDict(frozen=True, extra="forbid")


class ReplacementOrderPayload(BaseModel):
    order_id: str = Field(min_length=1)
    product_sku: str = Field(min_length=1)
    replacement_reason: str = Field(min_length=1)
    shipping_address_hash: str = Field(min_length=1)

    model_config = ConfigDict(frozen=True, extra="forbid")


class RefundRequestPayload(BaseModel):
    order_id: str = Field(min_length=1)
    product_sku: str = Field(min_length=1)
    refund_amount_cents: int = Field(gt=0, le=100_000)
    refund_reason: str = Field(min_length=1)

    model_config = ConfigDict(frozen=True, extra="forbid")


class WarehouseRepairReportPayload(BaseModel):
    product_sku: str = Field(min_length=1)
    batch_id: str | None
    defect_description: str = Field(min_length=1)
    severity: Literal["low", "medium", "high", "critical"]
    session_id: str = Field(min_length=1)

    model_config = ConfigDict(frozen=True, extra="forbid")


__all__ = [
    "RefundRequestPayload",
    "ReplacementOrderPayload",
    "WarehouseRepairReportPayload",
    "WarrantyClaimPayload",
]
