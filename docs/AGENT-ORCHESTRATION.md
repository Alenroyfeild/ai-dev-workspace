# O2: write-capable workers

Status: approved with Claude's 2026-10-13 decisions below. No write worker is enabled by this document.

## User result and scope

A developer gives one bounded implementation task to a worker, keeps using their
own checkout, and receives a diff with checks they can review before accepting it.
The worker cannot accept its own changes. Existing explorer/reviewer delegation
stays read-only; existing manual worker preparation stays available.

O2 covers one worker per run, its own git worktree, and explicit review before
integration. Splitting tasks, scheduling parallel workers and combining their
results belong to O3. No server, new provider abstraction or automatic publishing.
macOS with Codex and Claude Code comes first; other clients keep their current
preparation-only behavior until their execution boundary is proved. Linux/Windows
and existing client fixtures must keep passing.

## Reuse and ownership

Reuse `route()` for explicit provider/model selection, `worker_command()` for
argument construction, the existing bounded redacted brief, claims, atomic writes
and run logs. Add the write lifecycle beside `delegate()` in `ws/orchestration.py`;
do not weaken the existing explorer/reviewer command or its self-test. Keep the
lead as the only writer of task memory and final acceptance records.

Each run records: task/claim identity, provider/model, source repository identity,
pinned base commit, owned checkout path, state, exit status, diff identity, actual
check results and any known token usage. Unknown usage remains unknown. Local run
metadata and raw output stay under the private workspace's excluded `.ws/` tree.
Reuse the existing run log for summaries rather than introduce another database.

## Worktree and execution boundary

1. Validate the declared source repository and task claim. Refuse a missing base,
   ambiguous repository, submodules or linked dependencies requiring extra roots
   in the first version. Show the exact base, provider, scope and paths in preview.
2. Create a private local clone without shared object links, then one named worker
   worktree inside that run directory, pinned to the source commit. Do not attach
   workers directly to the user's repository: linked worktrees share Git metadata.
   Do not copy ignored files, credentials or uncommitted source edits implicitly.
   A dirty source checkout is allowed only with an explicit committed-base warning.
3. Give the worker its brief and checkout. It edits files and runs named checks;
   the lead creates any snapshot commit after collection. It never commits,
   pushes, merges, edits task memory or writes client settings in the user's HOME.
4. Enforce isolation outside the prompt: writes only in the worker checkout and
   disposable scratch space; original repo, private workspace and sibling runs
   inaccessible to writes; secrets inaccessible to worker tools. Git metadata and
   effective client settings stay protected from worker changes. Network from
   worker shell commands is disabled. Model authentication is handled by the
   trusted client, never copied into the checkout or passed in the brief.

Git worktrees separate checkouts, not permissions. The approved macOS v1 boundary
is the client's native OS sandbox: Codex `--sandbox workspace-write` (Seatbelt)
or Claude Code's filesystem write allowlist, with shell network access disabled.
No additional VM/container is required. The hostile self-test is still the gate:
if it fails or cannot run for a client, that client stays preparation-only.
No dependency installation, permission bypass or weaker provider fallback to
make a run work. Codex comes first; Claude runs its own worker probe.

## Proposed flow

The exact CLI spelling is subject to review. The smallest extension is a separate
explicit worktree option on worker delegation; ordinary `delegate --run` retains
its current read-only role checks. Preview creates no checkout and starts no client.
Before launch, one confirmation shows the task, committed base, new local files,
provider, permitted checks and execution boundary; scripts may opt in explicitly.
Acceptance is a separate action and is never implied by launch or a worker exit 0.

| State | What exists / permitted next action |
|---|---|
| prepared | Validated preview; launch after confirmation. |
| running | Owned checkout and child process; cancel or collect. |
| needs-review | Child stopped; diff/check output unverified, with any blocking/cancellation reason. Lead review is bound to the exact snapshot here. |
| accepted | Reviewed snapshot fetched as a new source-repo branch; record the commit. |
| discarded | Lead explicitly discarded the owned run. |

Collection checks the checkout against the pinned base, including deletions,
binary files and untracked files. Report actual changed paths, any out-of-scope
edits, secret-scan findings, failed checks and missing evidence. Out-of-scope or
secret-bearing changes block acceptance; scan failure also blocks it. Tests from
the worker are evidence, never approval. Run validation again under the boundary
because edited test/build scripts can execute code.

Review binds to an immutable snapshot of changed bytes and the test results.
Only the lead records its review identity; a reviewer assistant may provide
findings but cannot accept. Edits after review invalidate that review. Claim changes block
task-memory updates; preserve collected output for inspection without stealing
the claim. The worker's instructions and output cannot change this state machine.

## Acceptance, cancellation and recovery

Explicit acceptance checks the reviewed snapshot and claim again, then fetches
it into the source repository as a new branch `ws/worker/<run-id>`. Refuse an
existing branch; never switch checkouts or alter the active branch/index/files.
Show the new commit/diff; the user's normal PR flow handles integration and
publishing. No automatic push, PR merge, release or tag.
In this repository, Luna alone lands PRs.

Re-applying to an advanced target, conflict handling and separate integration
checkouts belong to O3. v1 preserves the reviewed snapshot and its pinned base.

Cancellation stops the child and its descendants, collects partial output and
leaves the checkout inspectable. Timeout is not completion. Restart reports an
interrupted running record; it never resumes a paid client automatically. Remove
only a recorded owned checkout after explicit discard or preserved acceptance;
dirty work is retained by default. Never force-remove another run's worktree.

## Proof required before implementation can be enabled

- Fixture lifecycle: missing base/claim, dirty source, refused extra roots,
  launch failure, timeout/cancel descendants, interrupted launch/collection,
  changed claim, stale review, existing acceptance branch and conservative cleanup.
- A hostile real-client probe with a positive control: worker edits an allowed
  fixture file and runs its test, while attempts to write the original repo,
  sibling run, workspace, HOME/config, Git metadata and symlink escapes fail;
  credential reads and shell network attempts fail. Verify effects on disk.
- One macOS live Codex run fixes a failing test in a sample repo, returns a diff,
  and leaves the original checkout unchanged before acceptance. A second run
  changes reviewed bytes and proves acceptance refuses the stale review.
- Claude runs the matching live Claude Code checks. Codex does not launch Claude.
  Secondary clients keep fixture coverage; Linux/Windows CI stays green. Existing
  read-only delegation and manual preparation tests must remain green.

For this design PR: review the code connections and official documentation,
check links and whitespace. Claude's verdict approved the native boundary,
private clone, five states and acceptance branch. No execution proof, benchmark
or installation is claimed by this design document.

## Official references and decisions for Claude

- [Git worktree](https://git-scm.com/docs/git-worktree): linked worktrees share
  repository data except per-worktree files; this is why workers use a private clone.
- [Codex noninteractive execution](https://learn.chatgpt.com/docs/non-interactive-mode):
  client permission controls are inputs to a tested boundary, not a worktree sandbox.
- [Claude worktrees](https://code.claude.com/docs/en/common-workflows#run-parallel-sessions-with-worktrees)
  and [sandboxing](https://code.claude.com/docs/en/sandboxing): native worktree
  support and shell isolation are separate mechanisms.
- [Claude permissions](https://code.claude.com/docs/en/permissions): bypass mode
  skips protections and is excluded from this proposed execution path.

Claude review needed: the Claude-worker native-sandbox hostile probe after the
launch and gate interface is implemented. Codex does not run that client.
