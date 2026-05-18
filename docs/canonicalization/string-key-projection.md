# `_string_key` Canonical Projection Doctrine

Status: ACTIVE
Cluster: Canonicalization Doctrine (F-08, F-16, F-27, F-28, F-29, F-30)
Binds: F-28 (raw `sorted()` over arbitrary Mapping keys → `_string_key`-projected sort)
Precedence: This doctrine MUST be codified before any substrate adopts the `_string_key` projection in production code paths. Its commit timestamp is part of the replay-evidence chain.

---

## Purpose

When a substrate canonicalizes a Mapping, it MUST produce a deterministic key
ordering regardless of the runtime types of the Mapping's keys. The
`_string_key` projection is the substrate-local doctrine for achieving this
without resorting to cross-type comparison (which raises in Python 3) and
without introducing type-introspective canonicalization (which violates
substrate sovereignty).

---

## Scope

This doctrine binds the canonicalization helpers of the following substrates:

- `app/boundary/translation/serializers/canonical.py`
- `app/boundary/normalization/canonicalize.py`
- `app/hardening/serializers/canonical.py`
- `app/session/serializers/canonical.py`
- `app/organizational_intelligence/serializers/canonical.py`

Each substrate owns its own `_string_key` implementation. The doctrine is
shared; the code is not. Substrates MUST NOT import a shared `_string_key`
from a centralized utility module. This preserves substrate sovereignty and
prevents hidden coupling of canonical-form evolution across substrates.

---

## Specification

### Signature

`_string_key(key: Hashable) -> str`

### Coercion semantics

- If `isinstance(key, str)`: return `key` unchanged (identity passthrough).
- Otherwise: return `json.dumps(key, default=str, sort_keys=True)`.

The `default=str` parameter invokes Python's `str()` on any value `json`
cannot natively serialize, producing a total function from JSON's
perspective. The `sort_keys=True` parameter ensures that if the key is
itself a Mapping (rare; Mappings are not normally hashable), its serialized
form is order-stable.

### Ordering semantics

`sorted(keys, key=_string_key)` produces a deterministic ordering by
lexicographic comparison of the projected strings.

- For all-string keys: equivalent to alphabetical sort. No behavior change
  from a raw `sorted(keys)`.
- For mixed-type keys: cross-type comparison errors are avoided by reducing
  all keys to strings first.

### Stringification semantics

The projection of a non-string key is exactly
`json.dumps(key, default=str, sort_keys=True)`.

Implementations MUST NOT substitute `repr(key)`, `str(key)`, `format(key)`,
or any custom formatter. The chosen projection is part of the canonical
contract; alternative projections produce divergent canonical forms.

### Nested behavior

`_string_key` MUST be applied to every Mapping sort within the substrate,
including nested Mappings reached via the substrate's recursive
canonicalizer. A substrate that applies `_string_key` only at the top-level
sort and leaves nested sorts raw is constitutionally incoherent and MUST be
rejected at review.

### Stability guarantees

`_string_key` is deterministic for any key whose `_string_key` projection
is itself deterministic across Python invocations. This includes:

- `str`, `int`, `float`, `bool`, `None`
- `bytes`, `bytearray` (projected via the `default=str` fallback)
- `tuple` whose elements recursively satisfy these stability conditions
- any value whose `__str__` implementation is documented as
  hash-state-independent

`_string_key` is NOT guaranteed deterministic for keys whose `__str__`
depends on Python hash state (PYTHONHASHSEED) or on hash-iteration order
of an enclosed hash-based collection.

---

## Totality boundary (Option C — bounded totality with explicit undefined region)

`_string_key` is total over `Hashable` values: every Python value usable as a
dict key produces some string output. The function does not raise.

The canonical-form contract is valid only over the well-behaved input
domain, defined below.

### Defined region

A Mapping is in the defined region if every key satisfies one of:

- is a `str`, `int`, `float`, `bool`, or `None`
- is a `bytes` or `bytearray`
- is a `tuple` whose elements recursively satisfy this rule
- is any value whose `__str__` is documented (by its class) as
  hash-state-independent

For Mappings in the defined region, the canonical form produced via
`sorted(keys, key=_string_key)` is **byte-stable** across Python
invocations, hash seeds, and process restarts.

### Undefined region

A Mapping is in the undefined region if any key:

- is a `set`, `frozenset`, `dict`, or instance of a class whose `__str__`
  iterates a hash-based collection containing non-trivially-hashed elements
- contains the above transitively (e.g., a tuple whose element is a
  frozenset of complex objects)

For Mappings in the undefined region, the canonical form is technically
produced by `_string_key` but its byte-identity across Python invocations,
hash seeds, or process restarts is NOT guaranteed.

**Callers are responsible for pre-canonicalizing pathological keys**
before passing them to a substrate canonicalizer. For example, convert
`frozenset({obj1, obj2})` to `tuple(sorted(obj1, obj2))` before use.

### Why the boundary is doctrinal, not enforced

The substrate MUST NOT introspect keys at runtime to detect the undefined
region. Runtime enforcement would require type-introspective
canonicalization — examining the structure and members of each key — which:

- violates substrate sovereignty (the canonicalizer would acquire knowledge
  of arbitrary user types)
- introduces an open-ended performance cost on every canonicalization call
- creates a hidden coupling between the canonicalizer and user-domain types
- expands the canonical-form contract along an uncontrolled axis

The doctrinal boundary is the constitutionally correct alternative:
callers carry the responsibility; the doctrine documents the responsibility
explicitly; reviewers enforce the doctrine at code review.

---

## Replay-evidence semantics

This doctrine is itself replay evidence.

When future auditors reconstruct the canonical-form contract that produced
a persisted record, they MUST be able to determine:

- which `_string_key` doctrine was in force at the time of canonicalization
- whether the persisted record's keys fell within the defined region

The doctrine's git commit timestamp serves as the temporal anchor. The
doctrine MUST be codified BEFORE any substrate adopts the `_string_key`
projection in production code paths. Concurrent codification is forbidden:
the doctrine's temporal precedence is part of the replay-evidence chain.

Replay reconstruction MUST interpret persisted canonical forms according to
the doctrine version active at the time the record was produced. Current
doctrine MUST NOT retroactively reinterpret historical canonical forms
unless an explicit epoch-transition mechanism authorizes such
reinterpretation.

---

## Replay-impact classification (current adoption scope)

`_string_key` is adopted by `boundary/translation` under F-28. The substrate
has zero operational callers of `canonicalize_attributes` and zero
operational callers of `content_fingerprint`. The adoption is therefore
**constructively epoch-clean**: no persisted record's canonical form
changes under this adoption.

`_string_key` is already in use by `session`, `hardening`, and
`organizational_intelligence` substrates prior to this doctrine's
codification. Their adoption pre-dated the doctrine; this codification
documents the contract those substrates already implement. No
post-codification behavior change is implied for those substrates.

`boundary/normalization` does not yet use `_string_key`. F-08 and F-16 will
address its adoption under separate constitutional ceremonies.

---

## Evolution

This doctrine MAY be amended only through a Canonicalization Doctrine
Cluster review.

Material amendments — changes to coercion semantics, stringification
semantics, or the defined-region boundary — trigger a
canonicalization-epoch transition. The epoch transition mechanism is
deferred to the F-27 doctrine.

Non-material amendments — clarifications, documentation improvements,
typographic corrections — do not trigger epoch transitions but MUST be
recorded in the document's git history with explicit
"non-material amendment" annotation.

---

## Cluster-position context

This is the FIRST codified document of the Canonicalization Doctrine
Cluster. Subsequent doctrines will reference this document:

- F-27 epoch doctrine — first true replay-history bifurcation event
- F-08 custody-at-construction doctrine
- F-16 doctrine codification completion

This doctrine alone does NOT establish epoch semantics. Epoch semantics
are deferred to the F-27 doctrine.
