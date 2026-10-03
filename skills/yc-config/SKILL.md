---
name: yc-config
description: Use when choosing or changing YoungCrow agents, Claude Code or Codex clients, model IDs, effort, API connections, mission limits or project defaults.
---

# Configure mission agents

Configure the project once, then use explicit mission overrides. Native diagnostics are a separate,
bounded operation with a durable receipt. Mission development remains unavailable.

Read project instructions and selected profile/interview notes. Before a first write, follow
`personalizer` to establish adoption mode and verify any requested trial baseline. Reuse answers
and existing `youngcrow/agents.json`. Use `ingest-source` for referenced documents and
`govern-capabilities` for skill/MCP choices. An available tool is not automatically authorized.

Run from the project root (`python` may be the host's Python 3 command):

```bash
python3 -B scripts/missions.py --json config show
```

For each required role (`pm`, `tech_lead`, `developer`, `qa`), recover or ask for client, model and
effort. `integration_specialist` is optional. OpenAI through Codex uses `client: codex`;
Claude Code uses `client: claude`. The default connection is `authenticated`. API is explicit;
ask only for `credential_env`, an uppercase variable name, never its value. Do not read credentials.
Unchosen model IDs remain `null`. Inspect the actual executable to obtain the client's current
model/effort catalog. Use the native executable on Windows, not an npm shell launcher:

```bash
python3 -B scripts/missions.py client inspect --client codex --executable PATH --json
```

Choose an explicit model ID or `latest`, which resolves the account's current client recommendation
at each new check. This is not a promise of the provider's newest release. Inspection does not call
a model or prove compatibility. Report native profile gaps; never bypass them or change clients.

`effort` is `{level, native_value}`. Common `low`, `medium`, `high` retain those nominal labels for
both clients; use `native` and the exact `native_value` for another requested level. Otherwise
`native_value` is null. `native` with `client-default` omits the effort override, including for models
without effort control. Validate all other levels against the inspected model's supported options.
Configuration commands do not probe models or log in. Do not downgrade an unsupported choice.

Use the defaults unless the user requests a change: active PBIs and parallel agents default independently
to 3; correction cycles are fixed at 3. Ask only for missing mission/agent seconds, agent runs and deploy
attempts, which require positive integers.
API also requires a positive decimal string budget in USD. Deploy defaults to manual; automatic
records intent and does not publish anything.

Write a private candidate JSON with `schema_version: 1`, `agents`, `limits`, `deploy_mode`, using
[the schema in scripts/mission_config.py](../../scripts/mission_config.py). Validate it, then apply the already authorized choices:

```bash
python3 -B scripts/missions.py --json config validate --input vault/local/agents-draft.json
python3 -B scripts/missions.py --json config apply --input vault/local/agents-draft.json --expected-digest absent
```

For an existing config, replace `absent` with the digest just read. A conflict requires reading the
new state and reconciling choices; do not overwrite it. Missing choices may be saved as draft only
when the user wants to preserve them; list the remaining gaps. Unknown fields are errors.

Return choices, gaps, compatibility status and next step. Project changes do not rewrite existing
missions. Use `yc-missao` for overrides or a revision; never edit mission snapshots directly.

For an authorized diagnostic of a prepared mission, follow the manifest and recovery contract in
[the usage guide](../../docs/USAGE.md#mission-client-checks). The manifest names the mission/revision,
role, operation UUID, authorization reference, seconds, one run and optional API budget. Use only
the fixed `echo-v1` fixture. Then run `client check --manifest RELATIVE_PATH --executable PATH --json`.
Preserve the UUID when retrying or recovering; inspect `client runs --mission M001 --json` first.
An uncertain run blocks another check. Reconciliation needs reviewed termination and external-effect
evidence bound to hashes; it never resets consumption or kills a PID supplied by the user.
A successful diagnostic confirms only that specific run. It cannot start PBIs, merge or deploy.
