"""Service-layer base class.

Intentionally tiny. The single shared concern between services today is
a structured logger bound to the concrete service's module path, which
makes log correlation across orchestration calls trivial.

Resist the urge to grow this class. New behaviour belongs on individual
services until a real second consumer demonstrates the abstraction is
warranted — premature shared mechanics in service bases are one of the
hardest things to unwind later.
"""

from __future__ import annotations

import logging

from app.core.logging import get_logger


class BaseService:
    """Common service-layer plumbing.

    Subclasses declare their explicit dependencies via `__init__` and
    call `super().__init__()` exactly once. Never use module-level
    singletons for service state — each FastAPI request constructs a
    fresh service instance through dependency injection.
    """

    logger: logging.Logger

    def __init__(self) -> None:
        self.logger = get_logger(self.__class__.__module__)


__all__ = ["BaseService"]
