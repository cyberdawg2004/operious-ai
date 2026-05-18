# Constitutional Risk Register

This document tracks latent constitutional, replay, chronology,
governance, lineage, dependency, and substrate integrity risks.

Purpose:
- preserve architectural memory
- prevent semantic drift
- track replay-sensitive asymmetries
- track governance weaknesses
- track substrate inconsistencies
- track future stabilization requirements

---

# Severity Levels

- Critical
  - threatens replay integrity, chronology integrity, or governance correctness

- High
  - likely to create future substrate instability or semantic drift

- Medium
  - architectural asymmetry or future maintainability concern

- Low
  - non-critical inconsistency or localized technical debt

---

# Status Types

- latent
  - exists but not currently causing operational instability

- active
  - currently affecting runtime or architectural integrity

- mitigated
  - partially stabilized but requires future review

- resolved
  - constitutionally stabilized and verified

---

# CR-001
## Canonicalization asymmetry across substrates

Severity:
Medium

Status:
latent

Risk:
Future semantic drift across replay-sensitive normalization boundaries.

Description:
Multiple substrates implement partially divergent canonicalization behavior.
Current stabilization restored defensive runtime guards in session canonicalization,
but equivalent canonicalization semantics are not yet constitutionally unified across all substrates.

Potential Consequences:
- replay normalization divergence
- inconsistent serialization behavior
- chronology reconstruction inconsistencies
- operational metadata asymmetry

Affected Substrates:
- session
- organizational_intelligence
- translation
- hardening

Replay Risk:
Low currently, potentially High after event fabric operationalization.

Recommended Future Action:
Perform constitutional canonicalization stabilization sweep after
Phase 2.3 operational mapping stabilizes.

Priority:
future stabilization sweep

---

# CR-002
## Aggregator composition validation asymmetry

Severity:
Medium

Status:
latent

Risk:
Inconsistent runtime composition guarantees across operational substrates.

Description:
organizational_intelligence aggregator composition currently assumes trusted
runtime composition while other substrates explicitly validate runtime boundaries.

Potential Consequences:
- inconsistent runtime defensive guarantees
- future replay reconstruction ambiguity
- runtime composition asymmetry
- hidden operational contract divergence

Affected Substrates:
- organizational_intelligence

Replay Risk:
Low currently.

Recommended Future Action:
Future runtime hardening phase should standardize composition validation doctrine.

Priority:
future hardening phase

---