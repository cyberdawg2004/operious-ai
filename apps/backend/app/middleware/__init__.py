"""ASGI middleware.

Each middleware module owns one cross-cutting concern (request
correlation, future: rate limiting, tenant routing, audit hooks). They
register against the FastAPI app in `app.main.create_app` so the
ordering and lifecycle stays in one reviewable place.
"""
