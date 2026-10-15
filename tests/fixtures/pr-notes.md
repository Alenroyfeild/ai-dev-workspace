## Task: T-1 — Fix crash

Source: `vault/Tasks/T-1.md` (saved task record; review before publishing).

### Objective
Crash on empty email

### Decisions and reasons
Decision: Store integer cents.
Reason: Avoid rounding.

### Checks (recorded, not rerun)
- Storage tests passed (saved result).
