# Principles

How this project decides what to build and when to ship.

1. **Measured, not claimed.** A claim in the README needs a reproducible run in `bench/` or a real-session check. Results are published even when the workspace does not win.
2. **The user's files, the user's assistant.** Memory is plain Markdown the developer owns. We use each assistant's own features (instructions files, hooks, skills, goals, memories) instead of replacing them.
3. **Across assistants by default.** Every memory change is checked with at least one different-assistant handoff, not only same-client runs.
4. **Small context.** The session-start brief stays under 200 words; details load on demand.
5. **Ask before acting.** Nothing is installed, deleted, posted or sent without a yes. Captures are redacted and marked unverified.
6. **Ship small and often.** A release goes out every week with what is ready and tested; unfinished work waits for the next one.
7. **Learn in public.** Mistakes found by tests, benchmarks or users become regression tests and lessons, and the CHANGELOG says what changed and why.
