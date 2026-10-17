# Team workspace

Keep personal work in your private workspace and share selected notes through a
private team repository. Everyone with access to that repository can read its
contents; review each preview before confirming.

## Quick start

Create an empty private repository. On GitHub or GitLab, the installed `gh` or
`glab` can verify privacy; otherwise attest that the exact remote is private.

```bash
ws team init <private-repo>
ws know add "Payments API rejects floats; send integer cents" --category domain --team
ws sync
```

A teammate runs `ws start` in their code repository, then links the team repository:

```bash
ws team link <private-repo>
ws brief
```

The brief places relevant team notes after your own decisions. Later, `ws sync`
pulls new notes and publishes only items you approved. `ws sync --daily HH:MM` can
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

## Privacy and recovery

Redaction is heuristic, not a guarantee. Inspect the preview and never share
secrets, credentials, personal transcripts or local paths. Team repository access
is repository-wide, not per note.

If sync reports a conflict, stop and resolve the named files manually; the
workspace does not reset history or ask an assistant to merge team records. For a
shared synced folder, link it with `--folder --attest-private`; the sync client
moves files, so partial or conflicting copies may need manual recovery. No sync
client is installed or configured for you.

For commands and options, see the [team command reference](COMMANDS.md#link-a-private-team-repo).
For sharing one workspace through Git, see [Team sharing](TEAM.md).
