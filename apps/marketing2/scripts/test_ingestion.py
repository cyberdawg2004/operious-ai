import asyncio
import uuid

from app.dependencies.memory import (
    build_document_ingestion_service_process_wide,
)

DOCUMENT = """
Operious AI provides enterprise operational intelligence systems.

Refund requests must be processed within 5 business days.

Customer escalations require supervisor review.
"""


async def main():
    service = build_document_ingestion_service_process_wide()

    result = await service.ingest(
        source="manual_test",
        content=DOCUMENT,
        metadata={"tenant_id": str(uuid.uuid4())},
    )

    print("\n===== INGESTION RESULT =====\n")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
