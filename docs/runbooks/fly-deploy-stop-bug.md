# Fly intermittent deploy-stop bug

## Summary
During a rolling `fly deploy` of `operious-ai-imad`, Fly has intermittently
stopped one random PRIMARY process-group machine and never restarted it,
even though `fly deploy` itself exits 0 (Fly considers the rollout
successful). The affected process group is different each time and the
event is not reproducible on demand. This is suspected to be a
platform-side Fly bug, not an application or config issue -- see "Config
leads ruled out" below for what we checked on our side first.

This doc is the evidence package for a Fly support ticket, plus the
interim mitigation we run until Fly resolves it. It is NOT a root-cause
finding -- the Fly CLI cannot identify the actor that issued the stop.

## Observed pattern
Each incident follows the same machine-event sequence:

```
pending -> created -> stopped(update,flyd)
```

with no subsequent `started` event, completing in ~2.5s, at deploy time.
`flyd` (Fly's own orchestrator) is the actor in the event log, not the
application or any user-initiated command.

## Known instances
| Process group | Version | Notes |
| --- | --- | --- |
| worker_ingress | v190 | reported by operator |
| worker_beat | v191 | reported by operator |

The Fly machine event log only retains the ~3-5 most recent events per
machine, so no further forensic detail (timestamps, exact event payload)
survives for these two historical incidents -- confirmed by querying a
live machine's event log directly, which showed only events from the
current deploy.

**Negative data point**: the `phase-2-2-stabilized` deploy to v197 on
2026-06-23 did NOT exhibit the bug -- all 11 primary process groups came
up `started` cleanly. This is consistent with the bug being intermittent
rather than triggered by every deploy.

## Config leads checked and ruled out
- `[http_service]` in `apps/backend/fly.toml` sets `auto_stop_machines =
  true`, `auto_start_machines = true`, `min_machines_running = 1`, but
  this block is scoped via `processes = ["web"]` to the `web` process
  group only. `worker_ingress` and `worker_beat` (the two known incident
  groups) have no `[http_service]` association at all, so Fly's
  traffic-based auto-stop mechanism cannot structurally explain either
  incident.
- There is no app-wide/top-level `auto_stop_machines` setting in
  `fly.toml` -- the only occurrence is the one scoped block above.
- Every worker `[[vm]]` block's `min_machines_running` already equals the
  number of primary (non-standby) machines currently running for that
  process group (confirmed via `fly scale show --app operious-ai-imad`,
  see table below) -- there is no scale-down headroom Fly could be acting
  on via a count-based autoscale decision.

```
NAME                  | COUNT | KIND   | CPUS | MEMORY  | REGIONS
web                   | 1     | shared | 1    | 1024 MB | iad
worker_beat           | 2     | shared | 1    | 256 MB  | iad(2)
worker_diagnostic     | 1     | shared | 2    | 1024 MB | iad
worker_escalation     | 1     | shared | 1    | 512 MB  | iad
worker_ingress        | 2     | shared | 1    | 512 MB  | iad(2)
worker_maintenance    | 1     | shared | 1    | 512 MB  | iad
worker_outbound_send  | 2     | shared | 1    | 512 MB  | iad(2)
worker_sme_approval   | 1     | shared | 1    | 512 MB  | iad
worker_sop            | 1     | shared | 1    | 512 MB  | iad
worker_supervisor     | 1     | shared | 1    | 512 MB  | iad
worker_voice_realtime | 2     | shared | 2    | 512 MB  | iad(2)
```

`fly scale` itself confirms the *desired* count for every affected group
(2 for worker_beat/worker_ingress/worker_outbound_send/
worker_voice_realtime, which is 1 primary + 1 standby) still includes the
machine Fly stopped -- Fly's own scale config wants it running.

## Fly support ticket (paste-ready)
> **App**: operious-ai-imad (Fly app), primary region iad
>
> **Issue**: Intermittent stop of a primary process-group machine during
> rolling deploy, machine never restarts, `fly deploy` exits 0 anyway.
>
> **Pattern**: machine event log shows `pending -> created ->
> stopped(update,flyd)` with no subsequent `started` event, ~2.5s
> duration, occurring at deploy time. Actor is `flyd` itself, not an
> application command or `fly machine stop` invocation.
>
> **Known instances**: worker_ingress process group at release v190;
> worker_beat process group at release v191. A different process group
> each time; not reproducible on demand (deploy to v197 on 2026-06-23 did
> not exhibit it).
>
> **Why we don't think this is our config**: the affected process groups
> have no `[http_service]`/`auto_stop_machines` association in fly.toml
> (that block is scoped to the `web` process group only via
> `processes = ["web"]`), and `fly scale show` confirms the desired count
> for the affected groups still includes the stopped machine -- Fly's own
> scale config wants it running.
>
> **Ask**: help identifying the actor/trigger behind the `stopped(update,
> flyd)` event for these two incidents (or future ones), since `fly
> history` is deprecated and the machine event log only retains the last
> 3-5 events, making the CLI insufficient for after-the-fact diagnosis.

## Interim mitigation
Until Fly resolves this, run
[`apps/backend/scripts/check_deploy_process_groups.py`](../../apps/backend/scripts/check_deploy_process_groups.py)
after every `fly deploy`:

```bash
python apps/backend/scripts/check_deploy_process_groups.py --app operious-ai-imad
```

It calls `fly status --json`, flags any machine that is `stopped` AND
does **not** carry a non-empty `standbys` config field (the field Fly
only ever sets on a machine configured as another machine's
hardware-failure standby -- never on a primary), and exits 1 if it finds
one. Pass `--restart` to have it call `fly machine start` on each one it
finds instead of just reporting:

```bash
python apps/backend/scripts/check_deploy_process_groups.py --app operious-ai-imad --restart
```

Verified against the current production state (v197, post the
2026-06-23 deploy): the script correctly reports `all primary process
groups started` and does not flag the app's two legitimate stopped
standby machines (worker_outbound_send†, worker_voice_realtime†).
