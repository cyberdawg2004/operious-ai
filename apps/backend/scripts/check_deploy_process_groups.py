#!/usr/bin/env python
"""Post-deploy guard for the intermittent Fly deploy-stop bug.

Fly has been observed (e.g. worker_ingress@v190, worker_beat@v191)
intermittently stopping one random PRIMARY process-group machine during a
rolling deploy -- pending -> created -> stopped(update,flyd), no
subsequent started event -- while `fly deploy` itself still exits 0,
because Fly considers the rollout successful. There is no known root
cause from the CLI side (see docs/runbooks/fly-deploy-stop-bug.md); this
script is the interim mitigation: run it after every `fly deploy` to
catch a stuck-stopped primary machine before a user does.

A machine is a legitimate STANDBY (expected to be stopped most of the
time) iff its Fly machine config carries a non-empty ``standbys`` list --
that field is only ever set on machines configured to stand by for
another machine's hardware failure, never on primaries. Anything stopped
WITHOUT that field is the bug, not by design.

Usage::

    python scripts/check_deploy_process_groups.py [--app operious-ai-imad] [--restart]

Exit codes:
    0 -- every primary process-group machine is started
    1 -- at least one primary process-group machine is stopped (printed to stderr)
    2 -- `fly status --json` itself failed (Fly CLI/auth/network problem)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def fetch_status(app: str) -> dict[str, object]:
    result = subprocess.run(
        ["fly", "status", "--app", app, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"fly status --json failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def find_stuck_primaries(status: dict[str, object]) -> list[tuple[str, str]]:
    """Return ``(machine_id, process_group)`` for stopped non-standby machines."""
    stuck = []
    for machine in status["Machines"]:
        if machine["state"] == "started":
            continue
        if machine["config"].get("standbys"):
            continue  # legitimate standby, expected to be stopped
        process_group = machine["config"]["env"].get("FLY_PROCESS_GROUP", "?")
        stuck.append((machine["id"], process_group))
    return stuck


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", default="operious-ai-imad")
    parser.add_argument(
        "--restart",
        action="store_true",
        help="call `fly machine start` on each stuck-stopped machine found",
    )
    args = parser.parse_args(argv)

    try:
        status = fetch_status(args.app)
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"check_deploy_process_groups: {exc}", file=sys.stderr)
        return 2

    stuck = find_stuck_primaries(status)
    if not stuck:
        print("check_deploy_process_groups: all primary process groups started")
        return 0

    print(
        "check_deploy_process_groups: stuck-stopped primary machine(s) found "
        "(Fly deploy-stop bug):",
        file=sys.stderr,
    )
    for machine_id, process_group in stuck:
        print(f"  - {process_group} ({machine_id})", file=sys.stderr)

    if args.restart:
        for machine_id, process_group in stuck:
            print(f"restarting {process_group} ({machine_id})...", file=sys.stderr)
            subprocess.run(
                ["fly", "machine", "start", machine_id, "--app", args.app],
                check=True,
            )

    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
