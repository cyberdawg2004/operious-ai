"""Document indexing subsystem.

`DocumentIngestionService` runs the explicit pipeline that takes raw
document text and produces:

* one `documents` row,
* N `document_chunks` rows,
* N `chunk_embeddings` rows,
* N vector records in the configured vector index,
* one `audit_event` and one structured execution log.

Nothing here is implicit, nothing is background, nothing decorates
itself. One method, one read.
"""
