"""Top-level intelligence-runtime aggregator.

`OrganizationalIntelligenceRuntime` is a **composition** of the
substrate's six runtimes. It exposes them as named attributes so
callers can route to the right semantic-ownership boundary:

    runtime.sop.ingest_sop(...)
    runtime.tonality.classify(...)
    runtime.communication.register_pattern(...)
    runtime.communication.retrieve_patterns(...)
    runtime.memory.propose(...) / approve(...) / reject(...) /
                  supersede(...) / retire(...) / list_artifacts(...)
    runtime.patterns.analyze(...)
    runtime.recommendations.generate(...) / record_review(...)

The aggregator does NOT route, NOT orchestrate, NOT execute.
It is a typed namespace.
"""

from app.organizational_intelligence.runtime.aggregator import (
    OrganizationalIntelligenceRuntime,
)

__all__ = ["OrganizationalIntelligenceRuntime"]
