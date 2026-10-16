# Parallel worker plans and reviewed unit branches

Status: design note for an unreleased feature. No parallel execution is enabled.
Rendering-integrity checks (#123) and a passing live Codex isolation check must land before implementation.
Rendering integrity is checked against the immutable collected tree. Claude
workers stay preparation-only until Claude completes the matching native-sandbox probe.
Known limit: Codex 0.155.1 sandbox permits /tmp writes; worker launch stays disabled.

## User outcome

The lead splits one claimed task into small independent units, previews their
scopes and checks, and confirms one plan. Each unit runs in a separate private
clone. The lead reviews each collected snapshot and explicitly accepts selected
results as `ws/worker/<run-id>` branches. The lead merges those branches through
the normal branch/PR flow. Disjoint scopes make conflicts rare; the lead resolves
any conflicts through that same review process. Worker execution and acceptance
leave the user's checkout, branch, index and dirty files untouched.

## Smallest first version

- One parent task, one declared source repo, one common committed base, one lead claim.
- Independent units in one wave; no dependency graph or automatic task generation.
  Dependent work becomes a new plan after the preceding result is integrated.
- Default concurrency two, bounded to one through four; no nested worker spawning.
- Codex only where the live isolation check has passed. No provider fallback or installation to make a run work.
- Reuse O2 preparation, native permission profiles, collection, review, acceptance,
  process-group cancellation and owned-path cleanup; do not extend route/delegate.
- Lead proposals and worker output are untrusted data. They cannot grant paths,
  change checks, accept output, raise concurrency or turn on network access.

## Plan and preview

CLI spelling is provisional: `ws worker plan <task>` previews a supplied unit list;
confirmation creates the local plan. `ws worker plan run <id>` confirms launch.
A plan holds its ID, source, pinned base, parent task revision, lead claim binding,
concurrency, deadline, units and run IDs. Each unit names its objective, normalized
path scope and exact check commands. Secrets/claim tokens are omitted from previews.
All records live outside the source repo under `.ws/worker-plans/<id>`.

Preview lists every directory/file to create, selected client/model/effort,
per-run filesystem/network permissions, units, checks and concurrency. No cloning,
model call or task mutation happens before confirmation. Unavailable models and
unknown cost are shown honestly; actual usage comes from execution receipts.

Reject duplicate unit names, empty/rooted/escaping/protected scopes and intersecting
scopes (including ancestor/descendant directories). All units read the same base;
only their own checkout/scratch are writable. Source repo, parent workspace,
siblings, HOME/config, credentials and Git metadata stay outside worker write access.
Unit scopes are checked separately from checkout-wide sandbox write access:
collection rejects out-of-scope snapshots before unit acceptance.
Worker tools cannot read private HOME/config or credentials outside the run; the
profile grants reads only to runtime/toolchain, checkout, private Git metadata and
scratch. Scratch contains no authentication secrets; authentication stays with
the trusted client broker. No global configuration or skills links are added.
No caller-supplied extra roots.

## Execution and collection

Create independent O2 runs for the parent claim; do not create child task IDs.
A short lead-side lock binds each run to the plan; release it before client execution.
The scheduler launches at most the confirmed concurrency and records start/finish,
exit/check evidence, immutable tree/diff identities and available usage per run.
Workers cannot update the parent task or each other's receipts.

A failure stops admission of queued units; retain already-running units until
completion or explicit cancellation. Failed/cancelled output stays inspectable;
it is never accepted automatically. A blocked run is final and needs a new run.
The plan deadline bounds every worker. Record each run's process-group ID and start
time. Timeout/cancel terminates each child process group and records unfinished units.
After restart, report a run whose recorded group is still alive as
`interrupted-running`. `ws worker cancel <id>` terminates only that group, and only
when its start time still matches the recorded value (PID reuse guard). No automatic
kill or resume after restart.
Claim or task-revision changes block further launch/acceptance without stealing
ownership. Retain existing runs and accepted commits for inspection.

| Plan state | Meaning / next explicit action |
|---|---|
| prepared | Confirm launch, inspect, or discard owned artifacts. |
| running | Collect independent results; cancel remaining work explicitly. |
| interrupted-running | Recorded group survived restart; inspect or explicitly cancel with the start-time guard. |
| needs-review | Review units; blocked units require replacement in a new plan. |
| accepted | Selected units have reviewed O2 branches; merge through the normal PR flow. |
| discarded | Owned artifacts removed; tombstone and accepted source branches retained. |

## Review and acceptance

For each unit, use O2 lead review and acceptance to create `ws/worker/<run-id>`.
Approval binds the displayed diff to immutable tree/check identities. Required
checks must run against that same collected tree; any later edit invalidates their
evidence and requires collection and checks again before acceptance. This matching
check-input identity is an O3 implementation requirement, not a claim about current O2.
Later checkout edits are excluded and warned about; acceptance uses the reviewed commit.
The warning can appear for unchanged files with Git eol normalization.

The lead merges accepted unit branches through the normal branch/PR flow.
Failed or unselected units remain visible; acceptance does not mark the parent task
finished. No automatic checkout switch, push, PR merge, release or tag.
Discard touches only recorded owned paths and never removes accepted source refs.

Reviewed integration clone: later, if users need it.

## Proof and implementation slices

1. Plan/preview: focused fixtures for claim drift, overlaps, bad roots, dry-run and
   interrupted preparation; no client execution.
2. Scheduler: bounded concurrency, isolated receipts, timeout/cancel descendants,
   failed admission, crash-surviving groups, start-time mismatch on cancel and
   restart without paid resume. A fixture changes a collected
   tree after passing checks and verifies acceptance requires collection and checks
   again on the new tree. No launch until the live isolation check passes.
4. One live Codex sample task: two independent edits/checks, reviewed branches,
   per-unit checks, lead confirmation and clean undo. Hostile attempts
   against source/workspace/HOME/Git/sibling/escape paths remain denied. Claude runs
   its own worker probe; other clients keep their existing support and fixture tests.

Each implementation PR stays near 300 lines, tests first, focused checks plus CI.
No benchmarks. This design PR stops at review; it does not authorize implementation.

## Official references

[Git worktrees](https://git-scm.com/docs/git-worktree) share repository metadata;
O2's private clones are the isolation building block here.
[Git merge](https://git-scm.com/docs/git-merge) documents the normal branch merging
flow; conflicts remain the lead's responsibility.
[Git update-ref](https://git-scm.com/docs/git-update-ref) supports expected-old-value
checks for conservative branch creation.
[Codex permissions](https://learn.chatgpt.com/docs/permissions) and
[noninteractive execution](https://learn.chatgpt.com/docs/non-interactive-mode)
define the native boundary and execution receipts; they do not replace live proof.

Still needed: a Claude-worker probe. Implementation waits for the live Codex isolation check.
