# Install the workspace skills

The repository provides `handoff`, `pickup`, `lesson` and `thinkbeforeact`.
They use the [Agent Skills format](https://agentskills.io/specification): a
`SKILL.md` with a name, description and instructions inside each `skills/<name>/`
directory. The compatibility field states their runtime prerequisites.

First install the workspace CLI using [Setup](SETUP.md), put `ws` on PATH and run
`ws start` in your code repo. Installing skills alone does not install the CLI,
connect MCP, create memory or enable hooks.

With Node/npm already available, inspect the repository's skills:

```sh
npx skills add Alenroyfeild/ai-dev-workspace --list
```

Then run the interactive installer from your code repo:

```sh
npx skills add Alenroyfeild/ai-dev-workspace
```

Choose the skills and clients you want. Keep project scope, inspect existing-name
conflicts and review files before committing them. Avoid a second installation if
your Claude plugin already provides these skills. The upstream installer owns its
files; `ws start --undo` only removes workspace wiring.

Repository shorthand reads the default branch. To inspect unreleased dev content:

```sh
npx skills add https://github.com/Alenroyfeild/ai-dev-workspace/tree/dev --list
```

Repository installs do not require a separate registry manifest. Listing or
promoting the skills on skills.sh is a separate maintainer action.

The discovery contract was checked against [Vercel Skills' source](https://github.com/vercel-labs/skills/blob/a80e4c9d12d607631249d4d7d059f835d4b2f13a/src/skills.ts)
and [source resolution](https://github.com/vercel-labs/skills/blob/a80e4c9d12d607631249d4d7d059f835d4b2f13a/src/source-parser.ts)
(MIT). Our instructions remain our own; no upstream code or skill text is included.
