# Operious AI Demo and Pilot Tenant Separation

## Summary

| Tenant ID | Purpose | Status |
| --- | --- | --- |
| `anker-pilot` | Demo (live now) | Active |
| `anker-production` | Pilot (future) | Reserved |

## anker-pilot (Demo Tenant)

`anker-pilot` is the live demonstration tenant shown to prospective clients, including Jiao Ma at Anker Innovations.

It contains five canonical proof sessions with real LLM classifications at 0.82-0.97 confidence. These sessions must not be deleted, modified, or regenerated.

Access:

```text
X-Tenant-ID: anker-pilot
URL: https://app.operious.com
Auth0: operious-dev.uk.auth0.com
```

Canonical session IDs:

| Scenario | Session ID | Confidence |
| --- | --- | ---: |
| `charging_allow` | `df6139ba-81fa-5f1d-9b3e-ceba6e7bb135` | 0.93 |
| `refund_over_limit` | `5bb139de-079b-5c20-a2da-3660b203a576` | 0.97 |
| `arabic_language` | `79b38add-3086-55f1-9820-db820697fb13` | 0.82 |
| `product_defect` | `2432a590-f7bc-5d5d-97f9-94a7d0039851` | 0.91 |
| `ambiguous_review` | `2e16bdcc-c518-504e-952c-b4e3d11cad41` | 0.82 |

Reset verification command:

```bash
python scripts/demo_seed.py --verify-only
```

The script verifies presence only. It does not rerun Anthropic, does not delete sessions, and does not modify canonical data.

## anker-production (Future Pilot Tenant)

When the Anker pilot begins, create `anker-production` separately from `anker-pilot`. It will have real ticket volume, real SOP documents loaded from Anker internal systems, and real governance policies calibrated with Anker operations.

It must never share data with `anker-pilot`. RLS enforces this at the database level, and application reads are scoped by tenant authority.

Pilot tenant creation rules:

```text
Tenant ID: anker-production
Do not copy rows from anker-pilot.
Do not reuse anker-pilot Auth0 tenant claims.
Do not load demo proof sessions into anker-production.
```

Use the existing tenant onboarding flow for channel configuration, knowledge documents, governance policies, topology configuration, and execution governance after the `anker-production` tenant row exists.

## Demo Access for External Stakeholders

A token with `tenant_id=anker-pilot` and no `operator` capability in JWT claims is already read-only by design. The system rejects any operator-only endpoint, including DLQ replay and quota circuit control, with HTTP 403 for non-operator tokens. No additional configuration is required to share read-only demo access.

To create demo access for Jiao Ma:

1. Create an Auth0 user at `operious-dev.uk.auth0.com`.
2. Assign the `anker-pilot` tenant_id claim.
3. Do not assign the `operator` capability.
4. Share login credentials and https://app.operious.com.

Recommended sharing paths:

| Option | Use When | Access |
| --- | --- | --- |
| Direct login | The stakeholder should inspect the live demo. | Auth0 user scoped to `anker-pilot`, no `operator` capability. |
| Recorded walkthrough | No system access is desired. | Screen recording of the five proof sessions. |
| Live demo call | First contact or executive walkthrough. | Imad shares screen from Command Center. |

## Data Isolation Guarantee

`anker-pilot` and `anker-production` are isolated at the PostgreSQL RLS level. An `anker-production` query cannot see `anker-pilot` data, and an `anker-pilot` query cannot see `anker-production` data.

This is enforced by FORCE RLS on all 38 tenant-scoped tables in migration `0034_force_rls`, by the production `operious_app` role running with `BYPASSRLS=False`, and by request authority propagation through the `X-Tenant-ID` or verified Auth0 tenant claim.
