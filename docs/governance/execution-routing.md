# Governance Execution Routing

Governance must remain:
- isolated
- explicit
- replay-visible
- chronology-visible

Operational execution should eventually route through:
- governance evaluation
- authority validation
- escalation evaluation
- policy enforcement

---

# Forbidden Patterns

The following patterns are constitutionally forbidden:

endpoint
→ service
→ database

direct orchestration
without governance visibility

runtime mutation
without chronology persistence

execution
without replay visibility

---

# Required Future Direction

Operational execution should converge toward:

request
→ normalization
→ envelope
→ governance
→ execution
→ chronology persistence
→ replay persistence
→ response