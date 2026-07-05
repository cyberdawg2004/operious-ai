# Operational drill scripts for Operious AI.
#
# Each drill script validates a specific resilience or security control by
# exercising it end-to-end against a target environment and printing
# PASS/FAIL with machine-readable evidence JSON.
#
# Run from the app container:
#   PYTHONPATH=/app python3 scripts/drills/<script>.py [args]
