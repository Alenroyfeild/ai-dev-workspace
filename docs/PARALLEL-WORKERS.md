# O3: parallel worker plans and reviewed integration

Status: design for Claude review. No parallel execution or integration is enabled.
O2c (#123) and the real Codex/all-tools O2d gate must land before implementation.
The unresolved O2c snapshot-rendering and warning-normalization findings are gates,
not assumptions that this design treats as fixed. Claude workers stay preparation-only
until Claude completes the matching native-sandbox probe.

## User outcome

The lead splits one claimed task into small independent units, previews their
scopes and checks, and confirms one plan. Each unit runs in a separate private
clone. The lead reviews each collected snapshot and explicitly accepts selected
results. A separate integration checkout combines only accepted commits, runs
checks under the native boundary, and presents one final diff for lead approval.
The user's checkout, branch, index and dirty files remain untouched throughout.
Publishing still uses the user's normal branch/PR flow.

## Smallest first version

- One parent task, one declared source repo, one common committed base, one lead claim.
- Independent units in one wave; no dependency graph or automatic task generation.
  Dependent work becomes a new plan after the preceding result is integrated.
- Default concurrency two, bounded to one through four; no nested worker spawning.
- Codex only where O2d has passed. No provider fallback or installation to make a run work.
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
collection rejects out-of-scope snapshots before unit acceptance or integration.
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
Timeout/cancel terminates each child process group and records unfinished units.
Restart only reports interrupted state; it never resumes a paid client implicitly.
Claim or task-revision changes block further launch/acceptance without stealing
ownership. Retain existing runs and accepted commits for inspection.

| Plan state | Meaning / next explicit action |
|---|---|
| prepared | Confirm launch, inspect, or discard owned artifacts. |
| running | Collect independent results; cancel remaining work explicitly. |
| needs-review | Review units; blocked units require replacement in a new plan. |
| integrating | Selected accepted commits are being combined in an owned clone. |
| conflict / failed-checks | Inspect retained integration output; no automatic resolution. |
| integration-review | Lead reviews the exact combined snapshot and check evidence. |
| accepting / accepted | Durable receipt precedes creation of the final branch. |
| discarded | Owned artifacts removed; tombstone and accepted source branches retained. |

## Review and integration

For each unit, use O2 lead review and acceptance to create `ws/worker/<run-id>`.
Approval binds the actual displayed diff to immutable tree/check identities, after
O2c rendering integrity is resolved. Later checkout edits are excluded and warned
about; acceptance uses the reviewed commit, not current mutable checkout bytes.
Do not merge a worker's live checkout or resolve a branch name again after selection:
pin every selected accepted commit/tree and the plan's current claim.

Preview a deterministic integration order and explicit target commit. If the target
advanced, show it and require a new integration preview; unit approvals remain
bound to their original snapshots. Create a fresh private integration clone from
that target, fetch only selected commit objects, and merge them in the shown order
with `--no-commit --no-ff`, hooks disabled (`core.hooksPath = os.devnull`),
isolated config and no shared
object store. After each clean merge, create a private merge commit before the next
merge; intermediate commits remain in the owned clone until final approval. Supply
the tool-owned commit identity per command, never by changing user Git config.
Never run merge drivers inherited from the source user's config.

Conflicts stop before the next merge. Keep the integration clone and conflict list;
no worker or scheduler silently resolves them. The lead may propose a resolution,
but changed resolution bytes require fresh integration collection, checks and review.
Do not change or rewrite unit acceptance branches.

Checks execute in the native sandbox, with network disabled and only the owned
integration checkout/scratch accessible. For validation, checkout/Git metadata are
read-only and generated outputs go to scratch; checks needing broader writes fail.
Collect the combined diff against the explicit target, scope/secret/binary/size
findings and command evidence. Checks are evidence, not approval. No integration
acceptance follows a failed check, stale claim or unreviewed snapshot.

Final lead confirmation creates `ws/worker-plan/<id>` at the reviewed integration
commit using an absent-ref comparison and a durable `accepting` receipt. Retry may
finish the exact matching ref or create a missing one; a different ref is refused.
Unselected/failed units stay visible in the final preview; acceptance does not mark
the parent task done. No ref deletion/rewriting, checkout switch, automatic push,
PR merge, release or tag.
Discard touches only recorded owned paths and never removes accepted source refs.

## Proof and implementation slices

1. Plan/preview: focused fixtures for claim drift, overlaps, bad roots, dry-run and
   interrupted preparation; no client execution.
2. Scheduler: bounded concurrency, isolated receipts, timeout/cancel descendants,
   failed admission and restart without paid resume. No launch until O2d passes.
3. Integration: accepted commits only, advanced target, conflict retention, final
   branch collision/recovery and immutable review; prove source HEAD/index/dirty files unchanged.
4. One live Codex sample task: two independent edits/checks, reviewed branches,
   combined sandboxed checks, lead confirmation and clean undo. Hostile attempts
   against source/workspace/HOME/Git/sibling/escape paths remain denied. Claude runs
   its own worker probe; other clients keep their existing support and fixture tests.

Each implementation PR stays near 300 lines, tests first, focused checks plus CI.
No benchmarks. This design PR stops at review; it does not authorize implementation.

## Official references

[Git worktrees](https://git-scm.com/docs/git-worktree) share repository metadata;
O2's private clones are the isolation building block here.
[Git merge](https://git-scm.com/docs/git-merge) supports explicit commits and stopping
before committing; conflicts require a separate reviewed resolution.
[Git update-ref](https://git-scm.com/docs/git-update-ref) supports expected-old-value
checks for conservative branch creation.
[Codex permissions](https://learn.chatgpt.com/docs/permissions) and
[noninteractive execution](https://learn.chatgpt.com/docs/non-interactive-mode)
define the native boundary and execution receipts; they do not replace live proof.

Claude review needed: plan scopes/concurrency, failure policy, immutable unit and
integration approvals, read-only validation, advanced-target/conflict behavior,
and the Claude-worker probe. No live Claude session was run.
