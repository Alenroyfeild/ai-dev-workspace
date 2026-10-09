# Sharing a workspace in a team

A workspace is plain Markdown, so a small team (2-5 people, one assistant each) can share it through a private git repo.

## Set up

```
cd my-workspace
git init -b main && git add . && git commit -m "Add workspace"
git remote add origin <your private repo> && git push -u origin main
```

Teammates clone it and run `ws connect claude` (or their client). Keep the repo private: it holds your decisions and task notes.

## Committed vs local

| Committed (shared) | Local (never commit) |
|---|---|
| `vault/` tasks, lessons, notes | `.ws/` claim tokens, run logs, caches |
| `workspace.json`, `routing.json`, `AGENTS.md` | `*.local.md` |

`.ws/` is in the generated `.gitignore`. `ws doctor` warns if it is not ignored or already tracked, and lists tracked vault lines that look like secrets (file:line only; remove and rotate them).

## How claims work across people

`ws claim T-1 alice-claude` writes `claimed_by` into the task file and a token into your local `.ws/claims`. Only the machine holding the token resumes the claim; everyone else sees `claimed elsewhere by alice-claude: ask before taking over`. Pull before you claim and push right after, so teammates see it.

The brief puts your own claims first, then the task whose `branch` matches the current branch of its repo, then an unclaimed active task. It lists teammates' work as `Others working: APP-2 (alice), APP-5 (bob)`; without a branch match it does not choose their task for you.

## Resolving a conflicted task

Two people editing one task file can leave `<<<<<<<` markers in it. Nothing crashes: `ws status` and `ws doctor` list the task as `conflicted` with a fix hint, and `claim`/`checkpoint` refuse until it is fixed.

1. Open `vault/Tasks/<ID>.md`, keep one side (or merge both), delete the `<<<<<<<`, `=======`, `>>>>>>>` lines.
2. `git add vault/Tasks/<ID>.md`, finish the merge, then run `ws validate`.

If both sides claimed the task, keep one `claimed_by` and `claim_token`; the other person runs `ws release` or picks another task.
