"""`TranslationNormalization` — recordable normalisation evidence."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TranslationNormalization:
    """One normalisation summary.

    Attributes:
        original_fingerprint:    SHA-256 over the original text.
        normalized_fingerprint:  SHA-256 over the normalised text.
        normalised_length:       Length of the normalised text.
        steps:                   Sorted, deduplicated list of
                                  applied normalisation steps.
    """

    original_fingerprint: str
    normalized_fingerprint: str
    normalised_length: int
    steps: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.original_fingerprint:
            raise ValueError(
                "TranslationNormalization.original_fingerprint "
                "must be non-empty"
            )
        if not self.normalized_fingerprint:
            raise ValueError(
                "TranslationNormalization.normalized_fingerprint "
                "must be non-empty"
            )
        if self.normalised_length < 0:
            raise ValueError(
                "TranslationNormalization.normalised_length "
                "must be >= 0"
            )

    @property
    def is_no_op(self) -> bool:
        return (
            self.original_fingerprint
            == self.normalized_fingerprint
        )


__all__ = ["TranslationNormalization"]
