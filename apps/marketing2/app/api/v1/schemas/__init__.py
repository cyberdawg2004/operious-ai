"""v1 transport schemas (Pydantic).

Each domain owns a module here (`health`, future: `agents`, `runs`,
`memory`, ...). Schemas are intentionally not eagerly re-exported from
this package — consumers import from the specific module to keep
dependency graphs explicit and shallow.
"""
