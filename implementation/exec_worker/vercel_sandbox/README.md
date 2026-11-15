# Vercel Sandbox evaluation (2026-11-15)

This folder contains an opt-in **fixed harmless Python command** probe, not an enabled
learner execution backend. Nothing imports it from the API or replaces gVisor.

## Verified provider information

The official npm SDK is `@vercel/sandbox`, pinned here to 4.0.0 (registry checked
2026-11-15). Its published SDK source was inspected for credential extraction and
delete options. Official references:

- https://vercel.com/docs/sandbox/sdk-reference
- https://vercel.com/docs/sandbox/concepts/authentication
- https://vercel.com/docs/sandbox/pricing

The current Hobby allowance includes 5 CPU hours, 420 GB-hours memory, 5,000
creations, and 20 GB transfer monthly. Hobby pauses on exhaustion instead of
charging overage; Pro is metered. Account plan and remaining allowance have NOT
been verified. Do not assume this account qualifies for free usage.

## Run

From this directory, run `npm ci`, then `npm test`. For the explicitly authorized
remote smoke command, export either `VERCEL_OIDC_TOKEN` or the complete
`VERCEL_TOKEN`, `VERCEL_TEAM_ID`, `VERCEL_PROJECT_ID` set; then run `npm run smoke`.
Do not commit credentials or place them in guest environment variables.

The full probe creates two separate disposable microVMs. Each uses deny-all
networking from creation, opens no ports, receives no host environment, mounts no
source, disables persistence, requests one vCPU, and has a 30-second session
limit. Each creation request has a 45-second client deadline; each command has
a 10-second client deadline. Provider command limits are two seconds for ordinary
checks, six seconds for the TCP/DNS check, and one second for the infinite-loop
check. Each deletion request has a 10-second client deadline. Both known VMs are
deleted in `finally`, including when one deletion fails. No retry is automatic.
An ambiguous creation failure may leave an unknown VM until its server-side
session timeout; cleanup cannot delete a handle the SDK never returned.

Preparation initially found no CLI credentials. The project owner subsequently
executed the fixed Python and extended smoke successfully using an authorized
OIDC context. This README is implementation documentation, not a replacement for
the owner's saved live run evidence. Offline unit tests never create cloud VMs.

## Acceptance still required before learner execution

A successful probe proves basic API access only. Integration must preserve
revision/spec/case validation, fresh per-invocation VMs, bounded inputs/results,
trusted framing and trace provenance, subprocess/PID and memory/CPU limits,
output flood termination, cancellation and restart cleanup, and durable usage
quotas. Provider session/command timeouts do not establish those controls.

Use a reviewed immutable runner image and verified runtime manifest. Exercise
adversarial isolation tests for network/DNS, filesystem, process limits,
resource exhaustion, cancellation, result forgery, and trace tampering. Keep
public code execution disabled until these checks have evidence. The current
probe deliberately accepts no learner source or custom command.

Dependency audit: the SDK pins `@vercel/cli-config` to Zod 4.1.11, affected
by GHSA-mrhx-c7xc-m3w5. A scoped override produced an audit-zero dependency
tree but review found the CLI config bundles Zod internally, so that did not
prove remediation. The override was removed. npm audit reports four high
findings; obtain an upstream fix and reassess before production integration. The managed universal image supplies Python; it is
a mutable provider reference suitable only for this fixed smoke probe.

The extended probe also runs a second fixed Python command. It attempts TCP
`1.1.1.1:443` with a one-second socket timeout and DNS resolution of `example.com`
with a two-second signal deadline. Each operation has a two-second alarm and the
whole command has a six-second provider deadline. Both operations must fail,
and the command must emit exactly `VIVA_NETWORK_BLOCKED`; any successful
connection or DNS resolution fails the probe. It sends no application data,
accepts no destinations from callers, and prints no raw network errors. This is
a focused egress check rather than comprehensive isolation acceptance.

Further fixed probes inspect only the presence (never values) of these environment
names: `VCC_GNANI_API_KEY`, `VCC_GROQ_API_KEY`, `VCC_INTERNAL_WORKER_SECRET`,
`VERCEL_OIDC_TOKEN`, `VERCEL_TOKEN`, `GNANI_API_KEY`, `GNANI_STT_API_KEY`,
`GNANI_TTS_API_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, and `DATABASE_URL`. Passing this
check establishes absence of those names only, not absolute absence of secrets.
A fixed infinite Python loop prints a start marker and has a one-second provider
command deadline; success requires an explicit nonzero exit result followed by a
separate command observing its recorded PID absent from `/proc`. SDK 4.0.0 exposes
no termination-cause field, so the report deliberately sets
`timeoutCauseVerified: false`, even if bounded loop termination is observed.

Two independently created disposable VMs test a fixed `/tmp` marker. The first
writes it, the second must not see it, and the first must still read it afterward
as a positive control. Both deletions are attempted even when one fails. These
are fixed probes only; no learner code or remote input is accepted.

No allow-all networking positive-control VM is included. Therefore failed TCP/DNS
operations establish observed denial from this VM, but do not prove the firewall
caused the failure rather than external network conditions. Treat the report as
smoke evidence and retain the independent isolation acceptance requirement.

## Controls not established by these probes

The SDK resource setting provisions a one-vCPU VM with provider-assigned memory;
it does not expose the existing runner's per-invocation RSS/address-space,
subprocess/PID, file-size, or output-byte policies. One tiny loop exiting does
not establish CPU accounting or process-tree termination. The `/tmp` marker
check establishes separation of that file between these VMs; it does not test
read-only root filesystems, writable-path allowlists, disk quotas, symlinks, or
host filesystem escape prevention. No output flood is generated or accepted.

A safe follow-up design requires a reviewed runner image that launches a child
with the application's configured rlimits/cgroup controls, emits bounded trusted
results, and kills the complete process group on cancellation/output overflow.
Fixed finite checks could then allocate just above its small memory cap, create
at most its small child-process cap plus one, write at most its file-size cap
plus one, and emit at most its output cap plus one. Each needs a positive control
below the cap, a host-enforced deadline, cleanup, and an explicit observed reason
for denial. Do not use an unbounded allocation, fork bomb, disk fill, or output
flood to infer provider controls. Those additional checks are **not implemented
or accepted** because no such VIVA limit-enforcing runner is connected here.
