"""Service layer.

Services own orchestration and business logic. They:

* receive their concrete dependencies explicitly via constructor;
* never import FastAPI, request, or response types;
* never construct or commit transactions on behalf of unrelated work;
* return domain objects, never transport schemas.

Routers depend on services. Services depend on `app.db` / `app.core`
primitives. The dependency graph flows in one direction.
"""
