# Anker Demo Seed Kit

Phase 6-F creates a real Anker pilot demo path without mocks:

- Tenant-owned governance and execution configuration for `anker-pilot`.
- Five SOP/policy documents stored through `/api/v1/tenant/knowledge`.
- Knowledge indexing through `/api/v1/knowledge/documents/{document_id}/ingest`.
- Six real ticket ingress submissions through `/api/v1/boundary/translation/ingress`.
- Real dispatch through `/api/v1/coordination/dispatch`.
- Timeline checks through `/api/v1/session/{session_id}/timeline` and
  `/api/v1/session/sessions/{session_id}/events`.

The policy text is a pilot demo corpus based on public Anker support
language and must be replaced by Anker-approved production source text
before live customer handling.

## Dry Run

```bash
python apps/backend/scripts/anker_demo/seed_anker_demo.py --dry-run
```

## Live Run

The default live target is the production API:
`https://operious-ai-imad.fly.dev/api/v1`.

```bash
OPERIOUS_API_BASE_URL=https://operious-ai-imad.fly.dev/api/v1 \
ANKER_EMAIL_ROUTING_ADDRESS=support@anker-pilot.operious.com \
ANKER_EMAIL_CHANNEL_API_KEY=... \
ANKER_EMAIL_WEBHOOK_SECRET=... \
python apps/backend/scripts/anker_demo/seed_anker_demo.py
```

If the production API is using verified bearer auth instead of trusted
internal identity headers, pass `OPERIOUS_API_TOKEN`. The script will then
omit `X-Tenant-ID` and `X-Principal-ID` to preserve authority-source
singularity.

```bash
OPERIOUS_API_TOKEN=... python apps/backend/scripts/anker_demo/seed_anker_demo.py
```

For configuration-only proof without channel credentials:

```bash
python apps/backend/scripts/anker_demo/seed_anker_demo.py --skip-channel
```
