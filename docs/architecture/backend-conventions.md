# Operious AI Backend Conventions

## Core Architectural Principles

- main.py is composition-only
- routers contain no business logic
- services contain orchestration logic
- repositories isolate persistence access
- configuration must flow through Settings
- no direct os.getenv usage outside config.py
- all APIs must be versioned
- logging must use structured logger
- environment behavior must be configuration-driven
- AI providers must be abstracted behind interfaces
- orchestration systems must remain modular
- avoid premature abstraction
- optimize for operational durability over velocity

---

## Directory Responsibilities

| Directory | Responsibility |
|---|---|
| app/api | transport layer |
| app/core | cross-cutting infrastructure |
| app/services | business logic |
| app/orchestration | workflow execution |
| app/providers | external provider abstraction |
| app/memory | RAG + memory systems |
| app/repositories | persistence abstraction |
| app/models | database/domain models |

---

## Operational Rules

- Never place business logic in routers
- Never access environment variables directly
- Never couple providers directly to orchestration
- Never commit secrets
- Keep main.py thin
- Keep systems loosely coupled
- Prefer explicitness over hidden magic
- Avoid framework overengineering