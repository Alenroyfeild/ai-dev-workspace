# Team workspace proposal (T0)

**Status: design for review; the commands and formats below are not implemented.**
Claude's verdict is required before T1. This extends the plain-file model in
[Architecture](ARCHITECTURE.md). The existing [shared workspace workflow](TEAM.md)
continues to work; there is no automatic migration or change to its sharing rules.

## Two layers

Each developer keeps a private workspace outside the code repo, as created by
`ws start`. A separate private Git repository holds deliberately shared team
memory. Linking it creates a local clone under `.ws/team`; the private workspace
itself is never pushed by team commands. One team link per developer workspace is
the initial limit. No database, new service or provider dependency is required.

Proposed `workspace.json` key: `team_workspace`, with a stable team ID, local clone
path, remote and opt-in sync policy. Do not reuse the existing `team` setting.
Reject remotes containing embedded credentials. Store no tokens or home paths in
shared records. A link is local configuration, not permission to publish memory.

`ws team init` prepares a team repo; `ws team link <remote>` verifies and clones it;
`ws team unlink` removes the link, preserving private records and any local shared
changes for recovery. Each command previews affected paths and asks before writes
or network access. Unlink must not silently delete an unpushed clone.

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
records must never copy executable hooks, rules, skills, plugin config or commands.

Policy defaults to `share: ask`. Category auto rules, if approved later, need a
separate explicit opt-in preview naming the category, destination and network
behavior. A team scope flag or assistant instruction cannot enable those rules.
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
demand through search or `ws know show`; generated indexes contain references, not
all record bodies. Reading team context must not require a network connection.

## Sync, visibility and conflicts

`ws sync` explicitly pulls the linked clone and pushes only approved shared
projections. Preview the remote, direction and changed records before consent.
Git access is repository-wide; this design does not promise per-record permissions.
A successful clone or URL spelling cannot prove a repository is private.

Proposed first implementation: verify visibility through an already installed
host CLI, without reading credentials directly; GitHub is the first supported
host. Unknown visibility, public visibility, offline verification or missing CLI
stops publication with a clear reason. Never silently fall back to another remote
or an unverified push. Recheck visibility before each push. Other hosts remain
prepare-only until a verification policy is approved.

Serialize local writes, use atomic replacement and source-revision checks, and
restrict paths to the linked clone. Preserve unrelated edits. Diverged histories
or conflicts stop sync with affected paths and a manual resolution hint: no reset,
clean, force push or AI conflict resolution. Conflicted records are excluded from
briefs with a visible warning. Offline reads work; pending approved changes remain
local and are reported, never treated as remotely published.

Quiet session-start/after-share sync, `--daily HH:MM`, and `--watch` are separate
opt-ins, not defaults. Scheduling asks before installing a macOS launchd entry;
other platforms initially get an inspectable cron/Task Scheduler suggestion.
Neither path installs software. Watching polls only the team repo; it is not
instant or guaranteed realtime and stops cleanly. A server is out of scope.

Optional `publish_status` shares only a previewed author alias, task title and short
working-on line. It is off by default, never publishes a hostname or claim token,
and displays timestamps so stale teammate status is not mistaken for availability.

## Implementation and proof after approval

| Phase | Small deliverable | Required proof |
|---|---|---|
| T1 | Init/link/unlink and private-remote verification | Two disposable homes; fake host CLI; failed visibility produces no publish |
| T2 | Scope metadata and ask policy | Private by default; no automatic network/write from a scope flag |
| T3 | Share/unshare and team save options | Exact preview; private text absent; stale source rejected; history warning |
| T4 | Categorized knowledge and generated indexes | Both layers; safe paths; indexes do not expose private bodies |
| T5 | Brief/search/MCP across layers | Private correction wins; bounded context; live owned-provider check |
| T6 | Optional teammate status | Consent, minimal projection and stale-date label in two homes |
| T7 | Sync and optional scheduling | Two clones/local bare fixture; conflict/offline recovery; opt-in only |
| T8 | Optional polling | Bounded polling and clean stop; no realtime guarantee |

Tests use fixture homes, local bare repositories and fake visibility responses;
never a real workspace or real client config. Live Claude checks belong to Claude.
No model call is needed to test sharing, visibility, path safety or sync effects.

## Claude review decisions before T1

1. Accept GitHub-first, fail-closed visibility checks, or define a safe policy for
   unsupported private hosts. User attestation alone is not assumed sufficient.
2. Accept ask-only publication initially, with category auto rules and quiet sync
   deferred until their separate consent contract is approved.
3. Confirm projection boundaries, private-over-team precedence and repository-wide
   access limits. T1 starts only after the design verdict is recorded in the inbox.
