# Contributing

- **Feedback** – inside your workspace: `ws feedback add "..." --kind idea|bug|friction|praise`. To share it with the project: `ws feedback submit <n>` (preview), then `--yes`. See [docs/MAINTAINING.md](docs/MAINTAINING.md).
- **Bugs** – include `ws doctor` output and the exact command and error.
- **Packs** – see [docs/PACKS.md](docs/PACKS.md). Generic knowledge only; worker packs need a self-test.
- **Code** – standard library only in `ws/` and `mcp/`. One implementation in `ws/core.py`; front doors call it. Add a test for every invariant and a regression test for every bug. Run `python3 -m unittest discover -s tests`.
- **Docs** – short sentences, exact commands, no claims without a way to check them.
