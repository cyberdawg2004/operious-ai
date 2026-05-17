"""Failure-containment classifier.

Pure deterministic — given an originating substrate and a
tuple of substrates observed reacting to a failure, classify
whether the failure stayed inside its semantic boundary.

The classifier never recovers. It only returns one of:

* CONTAINED       — only the originating substrate observed.
* LEAKED          — at least one foreign substrate reacted.
* UNVERIFIABLE    — observers tuple is empty (caller didn't
                     supply observation evidence).
"""

from __future__ import annotations

from app.hardening.enums import (
    ContainmentClassification,
    SubstrateName,
)


def classify_containment(
    *,
    originating_substrate: SubstrateName,
    observers: tuple[SubstrateName, ...],
) -> ContainmentClassification:
    if not observers:
        return ContainmentClassification.UNVERIFIABLE
    foreign = {
        observer
        for observer in observers
        if observer != originating_substrate
    }
    if not foreign:
        return ContainmentClassification.CONTAINED
    return ContainmentClassification.LEAKED


class FailureContainmentClassifier:
    __slots__ = ()

    def classify(
        self,
        *,
        originating_substrate: SubstrateName,
        observers: tuple[SubstrateName, ...],
    ) -> ContainmentClassification:
        return classify_containment(
            originating_substrate=originating_substrate,
            observers=observers,
        )


__all__ = [
    "FailureContainmentClassifier",
    "classify_containment",
]
