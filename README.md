# Operious AI

**Governed Organizational Cognition Infrastructure.**

This is **not** an AI chatbot framework, an autonomous agent swarm, an orchestration
playground, or a workflow automation app. Operious AI is deterministic enterprise
operational runtime infrastructure with a strict architectural law:

- The **Runtime Layer** is deterministic.
- The **Intelligence Layer** evolves only through governed, asynchronous memory evolution.
- These two layers MUST NEVER merge.

The frontend exists to **visualize authority**, never to own it. Frontend convenience
must never bypass backend governance semantics.

## Repository layout

```
apps/
├── backend/           Python / FastAPI deterministic runtime substrates
├── marketing/         Next.js executive narrative site
└── command-center/    Next.js operational cognition dashboard

packages/
├── types/             Shared DTOs / API contract shapes (TypeScript)
├── contracts/         Pinned API surfaces and substrate trace shapes
├── sdk/               Typed API client + TanStack Query wrappers + auth-aware fetch
├── ui/                Enterprise design system primitives (Tailwind + Shadcn)
├── auth/              Frontend auth context placeholder (foundations only)
├── tracing/           Frontend tracing primitives (correlation continuity)
├── topology/          React Flow abstractions + topology renderers
├── observability/     Trace rendering, replay visualization, timeline utilities
└── shared/            Shared utility primitives (deterministic helpers)
```

## Architectural laws

1. **Frontend visualizes authority. Backend owns authority.**
2. Frontend MUST NEVER mutate operational semantics directly.
3. Frontend MUST NEVER own business logic.
4. Frontend MUST NEVER bypass governance.
5. Frontend MUST NEVER perform orchestration.
6. Frontend MUST NEVER become an execution authority.
7. All mutations require explicit backend confirmation — no optimistic operational mutation.
8. Typed contracts only. No duplicated schema definitions.
9. Deterministic rendering ordering everywhere.
10. UI localization ≠ cognition localization. Backend cognition is canonical English.

## Workspaces

This repository uses npm workspaces. Node `>= 20`, npm `>= 10`.

```bash
npm install
npm run dev:marketing
npm run dev:command-center
```

The Python backend is independent of the npm workspace tree. From `apps/backend/`:

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/pytest
```

## Demo Environment

Live demo: https://app.operious.com
Backend: https://operious-ai-imad.fly.dev

Five Anker proof sessions are live in tenant `anker-pilot` with real AI
classifications.

To verify demo state:

```bash
python scripts/demo_seed.py --verify-only
```

To view the demo, open https://app.operious.com, log in through Auth0 with an
`anker-pilot`-scoped account, and inspect the five Anker proof sessions.
