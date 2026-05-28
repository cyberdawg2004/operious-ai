"""Shared JSON boundary type aliases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeAlias, Union

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = Union[JsonScalar, "JsonObject", "JsonArray"]
JsonObject: TypeAlias = dict[str, JsonValue]
JsonArray: TypeAlias = list[JsonValue]
MetadataMap: TypeAlias = Mapping[str, JsonValue]

__all__ = [
    "JsonArray",
    "JsonObject",
    "JsonScalar",
    "JsonValue",
    "MetadataMap",
]
