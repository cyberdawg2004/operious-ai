"""AI provider abstraction layer.

The single, vendor-agnostic seam between the platform and any inference
backend. Modules in this package MUST NOT:

* know HTTP exists,
* import FastAPI,
* import orchestration / service / repository code,
* own retries, timeouts, or tracing — those are gateway concerns.

A concrete provider only knows how to take an `InferenceRequest` and
return an `InferenceResponse`, mapping vendor-specific exceptions onto
the platform's typed `AIProviderError` hierarchy. Everything else
(dispatch, retries, observability) lives in `app.ai`.
"""
