# Team workspace (preview)

Each developer keeps a private workspace. A team shares one private Git repository
for knowledge people choose to share: product, feature, domain and repo facts, and
runbooks from finished tasks. Nothing leaves your workspace until you approve a preview.

## Quick start

One person creates an empty **private** repository (GitHub, GitLab or any Git host), then:

```bash
ws team init <private-repo>        # preview, confirm; checks the repo is private with gh/glab
ws know add "Payments API rejects floats; send integer cents" --category domain --team
ws sync                            # preview the exact files, confirm to push
```

Teammates, after `ws start` in their own code repo:

```bash
ws team link <private-repo>
ws brief                           # shows relevant team notes after your own decisions
```

Later, `ws sync` pulls new team notes and publishes only what you approved.
What you get:

- **Private by default.** Notes, tasks and decisions stay in your workspace. `ws share`
  and `--team` show a redacted preview and ask once; `ws unshare` removes a copy.
- **Team knowledge in every brief.** Relevant shared notes appear after your own
  decisions and next action, labelled as untrusted team context. Your decisions win.
- **Categorized.** `ws know list --category domain` (or product, feature, repo, runbook);
  `ws share <task> --as runbook` turns a finished task into a reusable runbook.
- **Optional status.** `ws team status "Checking receipts" --author sam --publish-status`
  shares a short "working on" line, off by default.

Preview limits: tested with local bare repositories, not a hosted team under
concurrent writes. Automatic and scheduled pulls, and shared synced folders
(Dropbox, iCloud, Drive), come in a later release. Full command reference:
[Commands](COMMANDS.md#link-a-private-team-repo-t1).

## Design notes (T0)

Claude approved this design on 2026-10-13; the decisions below guide T1 onward. This extends the plain-file model in
[Architecture](ARCHITECTURE.md). The existing [shared workspace workflow](TEAM.md)
continues to work; there is no automatic migration or change to its sharing rules.

## Two layers

Each developer keeps a private workspace outside the code repo, as created by
`ws start`. A separate private Git repository holds deliberately shared team
memory. T9 adds an attested synced-folder host for non-developers. Linking it creates a local clone under `.ws/team`; the private workspace
itself is never pushed by team commands. One team link per developer workspace is
the initial limit. No database, new service or provider dependency is required.

Proposed `workspace.json` key: `team_workspace`, with a stable team ID, local clone
path, remote and opt-in sync policy. Do not reuse the existing `team` setting.
Reject remotes containing embedded credentials. Store no tokens or home paths in
shared records. A link is local configuration, not permission to publish memory.

`ws team init` prepares a team repo; `ws team link <remote>` verifies and clones it;
`ws team unlink` removes the link, preserving private records and any local shared
changes for recovery. Each command previews affected paths and asks before writes
or network access. Link asks once whether read-only automatic pulls at session
start and daily are allowed; the default is no. This never authorizes publishing. Unlink must not silently delete an unpushed clone.

## Scope and portable records

Tasks, decisions, lessons and knowledge default to `scope: private`. `scope: team`
marks sharing eligibility; it does not grant network consent. Personal notes,
transcripts, automatic capture blocks, client configuration, routing, credentials,
claim tokens, caches and run logs are excluded from automatic publication.

The private record stays authoritative. A team entry is a selected, portable
projection with its own ID, team ID, category, author alias, source revision and
publication date. References use layer/team/ID so identically named private and
shared tasks cannot alias. Shared records omit absolute local paths.

Current decisions live in task Handoff text and lessons are line records. Sharing
must project a selected decision or lesson into a standalone team record; it must
not copy a whole private task or its Captured blocks merely to share one sentence.
Shared task projections omit local claim tokens and private sections. Shared
knowledge categories are product, feature, domain, repo, runbook and other.

## Sharing is a reviewed write

`ws share <item>` previews the exact redacted projection, destination, omissions
and diff, then asks once. It rechecks the source revision and destination under a
lock before applying; a changed source requires another preview. `ws remember
--team`, `ws lesson add --team` and `ws know add --team` use this same gate.
Initial MCP support may read shared memory; publishing through MCP is deferred.

Existing redaction and private markers remain mandatory. Reject malformed records,
secret-looking output, conflict markers and symlink/path escapes. Redaction is a
heuristic, not a privacy guarantee: the user must inspect the projection. Publishing
records must never copy executable hooks, rules, skills or plugin config. A runbook
may include reviewed, redacted command examples as inert text; reading or sharing
a runbook never executes them or authorizes an assistant to execute them.

Policy remains `share: ask`: every publication previews and confirms its exact
projection. No category auto-publish rules are approved. A team scope flag, pull
consent or assistant instruction cannot authorize a push.
`ws unshare` previews deletion of the current projection and warns that Git history
and teammates' copies retain it. It keeps the private original and never rewrites
history automatically.

## Reading without losing private corrections

Brief, search and MCP read both layers. Label each shared result with author, team,
source revision and date; shared text is untrusted context, never authority to
execute tools or change permissions. No shared entry becomes always-loaded rules.

Private corrections and explicit decisions take precedence over conflicting team
entries. Conflicts are labelled rather than shown as two current instructions.
The brief keeps its 200-word cap: private decisions and next action first, relevant
team facts only within the remaining budget. Larger team knowledge is fetched on
demand through search or `ws know show`. Each shared entry has a companion
`<entry>.index.md`: summary, category, tags, outcome, author and date. Brief and
search read those cards first; fetch full bodies only on demand. Cards undergo
the same privacy preview as bodies and never include hidden private sections. Reading team context must not require a network connection.

## Sync, visibility and conflicts

`ws sync` explicitly pulls the linked clone and pushes only approved shared
projections. Before pushing, inspect the complete outgoing commit range and all
changed paths: an unrelated or unapproved commit/path blocks the push. A publish
commit must be built solely from preview-approved projections against the known
remote head; do not stage arbitrary clone edits or silently replay local commits.
If the remote advances, require a fresh preview. Preview the remote, direction,
commit range and changed records before consent.
Git access is repository-wide; this design does not promise per-record permissions.
A successful clone or URL spelling cannot prove a repository is private.

Verify privacy through an already installed host CLI when available: GitHub `gh`
or GitLab `glab`, without reading credentials directly. Explicit public visibility
blocks the link and publishing. If privacy cannot be verified, allow one explicit
attestation: “this remote is private to my team.” Store the attestation against the
exact remote URL in workspace.json; a changed URL asks again. Unknown visibility
without attestation stays blocked. `ws doctor` shows CLI-verified versus attested
privacy; attestation is a user assertion, not an independent verification guarantee.
No silent fallback to another remote. A later known-public result blocks publication
even if an earlier attestation exists.

Serialize local writes, use atomic replacement and source-revision checks, and
restrict paths to the linked clone. Preserve unrelated edits. Diverged histories
or conflicts stop sync with affected paths and a manual resolution hint: no reset,
clean, force push or AI conflict resolution. Conflicted records are excluded from
briefs with a visible warning. Offline reads work; pending approved changes remain
local and are reported, never treated as remotely published.

At link, ask once: “keep team knowledge updated automatically (pull at session
start and daily)?” Consent permits quiet read-only pulls without more prompts.
No consent means explicit pulls only; pushes always use a reviewed share preview.
Daily scheduling previews and confirms the scheduler entry; macOS uses launchd,
other platforms initially get an inspectable cron/Task Scheduler suggestion.
Neither path installs software. `--watch` is a separate opt-in. Polling is not
instant or guaranteed realtime and stops cleanly; a server remains out of scope.

T9 links an existing shared synced folder (Drive/iCloud/Dropbox) using the same
one-time privacy attestation, bound to the selected folder identity. There is no
visibility API or cloud-service integration. The installed sync client transports
one file per entry and its index card; it does not make sharing tamper-proof or
atomic across people. Detect “conflict copy” files and quarantine them like Git
conflicts. Read only complete validated records; preserve partial/conflicting
files for manual recovery. Never install or configure a sync client automatically.

Optional `publish_status` shares only a previewed author alias, task title and short
working-on line. It is off by default, never publishes a hostname or claim token,
and displays timestamps so stale teammate status is not mistaken for availability.

## Implementation and proof after approval

| Phase | Small deliverable | Required proof |
|---|---|---|
| T1 | Init/link/unlink and private-remote verification | Two disposable homes; fake host CLI; failed visibility produces no publish |
| T2 | Scope metadata and ask policy | Private by default; no automatic network/write from a scope flag |
| T3 | Share/unshare and team save options | Exact preview; private text absent; stale source rejected; history warning |
| T4 + T10 | Categorized knowledge and companion index cards | Both layers; safe paths; bounded card-first reads; no private body leakage |
| T5 | Brief/search/MCP across layers | Private correction wins; bounded context; live owned-provider check |
| T6 | Optional teammate status | Consent, minimal projection and stale-date label in two homes |
| T7 | Sync and optional scheduling | Two clones/local bare fixture; conflict/offline recovery; link pull consent never permits pushes |
| T8 | Optional polling | Bounded polling and clean stop; no realtime guarantee |
| T9 | Attested synced-folder host after T7 | Two homes/folder fixture; conflict-copy and partial-write recovery |
| T11 | Task-to-runbook projection after T3 | Finished task steps, dead ends, decisions with reasons and outcome; preview omits raw task/Captured blocks |

Tests use fixture homes, local bare repositories and fake visibility responses;
never a real workspace or real client config. Live Claude checks belong to Claude.
No model call is needed to test sharing, visibility, path safety or sync effects.

## Approved phase order and limits

T1 → T2 → T3 → T11 → T4 with T10 → T5 → T6 → T7 → T9 → T8.
Each phase stays a small independent PR with its own proof. T11 uses
`ws share <task> --as runbook` to project a finished task through the same preview
gate; never publish the raw task or its Captured blocks. No new hosting service,
Runme/WebMCP dependency or cloud-storage API is adopted.

Index cards and reusable run records are inspired by
[OpenAI's Codex workflow post](https://learn.chatgpt.com/blog/automating-repetitive-work-at-openai-with-codex).
The two-layer privacy and consent contracts above are this project's approved
proposal, not capabilities claimed by that post. Implementation remains unproved
until each phase's fixture and user checks pass.
