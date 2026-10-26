# Stop your AI assistant retrying a failed approach

An assistant that does not remember a dead end will try it again next session. `ai-dev-workspace` keeps dead ends in the task record and shows them in every session's start-up brief.

## Record a dead end

Save it with a checkpoint, using the `Do not redo` note section ([Commands](../COMMANDS.md)):

```sh
ws checkpoint fix-login --status in_progress \
  --next "Add the rate limit to /login" \
  --note "Do not redo=Session cookies were tried; they break the mobile app"
```

Replace `fix-login` with your task id (`ws task list`). Omit the id when you have one claimed task. Say what was tried and why it failed, in one line.

## See it in the next session

`ws brief` prints what hooks inject at session start in Claude Code, Codex and other connected assistants:

```text
Next action: Add the rate limit to /login
Do not redo: Session cookies were tried; they break the mobile app
```

`ws pr-notes` also lists tried-and-rejected approaches in PR text. The brief is context, not an order: an assistant can still ignore it, and hooks do not warn before it runs a command that failed before.

## Optional packs

Both are off by default. Turn one on, then run `ws start` again in each repo; it previews the hook change first:

```sh
ws pack add discipline
ws pack add guards
ws start
```

- **discipline** is advisory. After the same shell command fails 3 times in one session, the assistant is told once to stop, form one hypothesis and save the dead end with the command above. Counts are per command and per session; it stores a hash of the command, not the text.
- **guards** denies a few risky commands before they run: `rm -rf` on home or root, `git reset --hard`, force push, `git clean -f`, secrets in commands or files, and newly skipped tests. Start the assistant with `WS_GUARDS=off` to turn it off for one session.

Guards are a safety net for common mistakes, not a security boundary. A determined or creative command can get around pattern matching, so keep your normal permissions and review in place.

Remove a pack with `ws pack remove <name>`, or everything with `ws start --undo`.

## Try it safely

```sh
HOME=$(mktemp -d) sh -c 'cd $(mktemp -d) && git init -q && ws start --yes && ws checkpoint --status in_progress --next "Retry later" --note "Do not redo=Tried X; it fails" && ws brief'
```

The last line of output should include `Do not redo: Tried X; it fails`.

## Limits

- Only dead ends someone saved show up. The discipline nudge reminds the assistant, but the assistant still has to run the command.
- Codex hooks do not report an exit code, so discipline counts repeated identical output there instead; it is a loose match.
- Claude Code and Codex hooks are proven in real sessions; other clients are fixture-tested ([Client verification](../CLIENT-VERIFICATION.md)).
