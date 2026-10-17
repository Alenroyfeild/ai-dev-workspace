# Team workspace

**This page is the shared-repo (or shared-folder) mode: everyone keeps a private workspace and shares only approved notes. Pick it for most teams. To share one whole workspace through Git instead, see [Sharing one workspace through Git](TEAM.md).**

Keep personal work in your private workspace and share selected notes through a
private team repository. Everyone with access to that repository can read its
contents; review each preview before confirming.

## Quick start

Create an empty private repository. On GitHub or GitLab, the installed `gh` or
`glab` can verify privacy; otherwise attest that the exact remote is private.

```bash
cd ~/code/myapp && ws start           # once per code repository
ws team init <private-repo> --attest-private
ws know add "Payments API rejects floats; send integer cents" --category domain --team
ws sync                               # first sync also publishes the team manifest
```

`--attest-private` is needed unless `gh`/`glab` can verify a GitHub/GitLab remote.
At a terminal each command shows a short summary and asks `[y/N]`; in scripts and
pipes there is no prompt, so add `--yes` (the full preview prints as JSON).
Teammates cannot link until the host has run `ws sync` once.

A teammate runs `ws start` in their code repository, then links the team repository:

```bash
ws team link <private-repo> --attest-private
ws brief
```

The brief places relevant team notes after your own decisions. Later, `ws sync`
pulls new notes and publishes only items you approved, then prints one line such as
`Team sync: pulled 1 new, 0 updated; published 1.` `ws sync --daily HH:MM` can
schedule read-only pulls; pushes still require a reviewed preview.

## What can be shared

Tasks, decisions, lessons and knowledge are private by default. A team scope makes
an item eligible to share; it does not authorize a copy or a push. Use `ws share`
or `--team` on `ws remember`, `ws lesson add` and `ws know add` to see a redacted
preview and confirm the exact files. `ws unshare` removes the current shared copy
but cannot erase Git history or copies teammates already pulled.

Shared notes are labeled as team context and treated as untrusted text. Your own
decisions take precedence. Briefs and searches work from the latest local snapshot
when offline. `ws team status` can publish a short working-on line when you opt in;
it is off by default.

## Private markers

In text you share (`--team`, `ws share`), these stay out of the team copy:

- `#private` anywhere in a line drops that whole line.
- `<private>...</private>` drops only the span; an unclosed `<private>` refuses to share.
- Home and other local paths become `[local path]`; `key=value` secrets, Bearer tokens and keys become `[REDACTED]`.

A note saved without `--team` never leaves your machine, so the saved file keeps its text
(and paths) as written; only secret-looking values are still redacted. Its
summaries and indexes leave marked text out, and the markers are applied in full
when you later share it. `--team` text that is entirely private is
refused and not saved. Emails and phone numbers are not redacted: leave them out.

## Privacy and recovery

Redaction is heuristic, not a guarantee. Inspect the preview and never share
secrets, credentials, personal transcripts or local paths. Team repository access
is repository-wide, not per note.

A secret that was pushed stays in Git history even after `ws unshare` and a sync:
rotate it, then rewrite history if the repository must be clean.

If sync reports a conflict, stop and resolve the named files manually; the
workspace does not reset history or ask an assistant to merge team records. For a
shared synced folder, link it with `--folder --attest-private`; the sync client
moves files, so partial or conflicting copies may need manual recovery. No sync
client is installed or configured for you.

For commands and options, see the [team command reference](COMMANDS.md#link-a-private-team-repo).
For sharing one workspace through Git, see [Team sharing](TEAM.md).
