---
name: yc-status
description: Use when consulting a YoungCrow mission, its revisions, planning gaps, source freshness, history or pending projections without changing the project.
---

# Read mission status

Read project instructions and the requested mission identifier. From the project root:

```bash
python3 -B scripts/missions.py --json status M001
```

Replace M001 with the real code or UUID; `python` may be the host's Python 3 command.
This operation is read-only, including before initialization. Do not run personalizer, initialize
storage, import notes, apply defaults or repair projections as part of a consultation.

Report state/revision, planning gaps, `stale_inputs`, event times and projection state. Distinguish
frozen mission configuration from current project defaults. `prepared` means complete planning;
`runtime_available` and `runnable` remain false. Development/QA are not started and production is
unverified. Report client diagnostic receipts separately, with requested/resolved/observed model,
effort, connection, timestamps and limits. Unknown cost or observed model stays unknown.

```bash
python3 -B scripts/missions.py client runs --mission M001 --json
```

This also reads without initializing, migrating or repairing storage. A successful diagnostic
does not enable mission execution. A `reserved`, `running` or `uncertain` receipt blocks a new
check until resolved. Report the same operation UUID and the evidence needed for reconciliation;
do not issue a fresh UUID, replay the check or reconcile as part of a status request.

For missing or stale evidence, name the next action without performing it. Documents need
`ingest-source`; capability changes need `govern-capabilities`; refinement needs `yc-missao`.
For an explicitly requested repair, continue with `yc-missao`, whose reference covers adoption
and repair. Keep this consultation read-only and report pending/conflict honestly. A read-only
request does not authorize a repair, even when the next action seems obvious.
