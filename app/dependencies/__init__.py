"""FastAPI dependency providers.

Three small modules, each owning one wiring concern:

* `database`     — async session + session factory.
* `repositories` — repositories bound to a request session.
* `services`     — services composed from repositories and primitives.

Routers depend on `services` (and occasionally on `repositories`
directly for read-only auxiliary endpoints). Services and repositories
never import from this package — providers depend on them, not the
other way around.
"""
