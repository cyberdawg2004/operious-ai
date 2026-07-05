# OpenAI Embedding Rollout Runbook

## Overview

This runbook covers the procedure for migrating tenant knowledge embeddings from
the deterministic hash-based provider to the real OpenAI text-embedding-3-small
provider (1536 dimensions, native pgvector HNSW index).

**Script:** `apps/backend/scripts/reembed_knowledge_embeddings.py`

---

## When to run this

- When `EMBEDDING_DEFAULT_PROVIDER` is changed from `deterministic` to `openai`
- When adding a new tenant whose knowledge documents need to be embedded
- When `OPENAI_EMBEDDING_DIMENSIONS` changes (requires schema migration first)

---

## Prerequisites

1. `OPENAI_API_KEY` is set in Fly secrets and valid.
2. `EMBEDDING_DEFAULT_PROVIDER=openai` is set.
3. `OPENAI_EMBEDDING_DIMENSIONS=1536` matches the pgvector column dimension.
4. Production is healthy: `curl https://operious-ai-imad.fly.dev/api/v1/health`

---

## Step 1: Snapshot

Before re-embedding, record the current vector state:

```bash
fly ssh console --app operious-ai-imad --command "bash -c 'cd /app && PYTHONPATH=/app python3 scripts/reembed_knowledge_embeddings.py --tenant-id <TENANT_ID> --dry-run'"
```

This prints `before` vector counts and dimensions without writing anything.
Archive the output as evidence.

---

## Step 2: Dry run

```bash
fly ssh console --app operious-ai-imad --command "bash -c 'cd /app && PYTHONPATH=/app python3 scripts/reembed_knowledge_embeddings.py --tenant-id <TENANT_ID> --dry-run --provider openai'"
```

Verify:
- Document list looks correct
- No errors in dimension check
- Cost estimate is acceptable (1536-dim embeddings are ~$0.00002/document)

---

## Step 3: Re-embed

```bash
fly ssh console --app operious-ai-imad --command "bash -c 'cd /app && PYTHONPATH=/app python3 scripts/reembed_knowledge_embeddings.py --tenant-id <TENANT_ID> --provider openai'"
```

The script:
1. Iterates active, approved knowledge documents for the tenant
2. Chunks each document (deterministic chunker)
3. Calls OpenAI embeddings API
4. Upserts vectors into `tenant_knowledge_vectors` at 1536 dimensions
5. Prints per-document PASS/FAIL with before/after vector counts

---

## Step 4: Verify retrieval

After re-embedding, submit a test query to confirm retrieval works:

```bash
fly ssh console --app operious-ai-imad --command "bash -c 'cd /app && PYTHONPATH=/app python3 scripts/live_verify_intelligence_layer.py --tenant-id <TENANT_ID> --query \"test query\"'"
```

Verify citation scores are non-zero and retrieved documents match expectations.

---

## Rollback plan

If embeddings are corrupted or retrieval degrades:

1. **Immediate**: Set `EMBEDDING_DEFAULT_PROVIDER=deterministic` in Fly secrets → rolling restart.
   Retrieval still works (just with hash-based embeddings, lower quality).

2. **Delete bad vectors** (if needed):
   ```sql
   DELETE FROM tenant_knowledge_vectors 
   WHERE tenant_id = '<TENANT_ID>' 
   AND dimensions = 1536;
   ```
   Then re-embed from scratch with the corrected configuration.

3. **Restore from Neon PITR**: if vectors are corrupted beyond repair, restore the
   `tenant_knowledge_vectors` table from a Neon point-in-time snapshot.

---

## Dimension change procedure (rare)

If changing from 1536 to a different dimension:

1. Write a migration to alter the `tenant_knowledge_vectors` pgvector column dimension.
2. Drop and recreate the HNSW index.
3. Re-embed ALL tenants.
4. Update `OPENAI_EMBEDDING_DIMENSIONS` Fly secret.

**This is a breaking change** — do not change dimensions without testing on a Neon branch first.
