# Keep a workspace current

`ws assist` offers at most two local suggestions. It now checks for a newer kit
version or pending .ws-new proposals, installed but unconnected Cursor/VS Code/
Gemini clients, and routed read-only providers without an executed selftest.
It reuses the long-session warning: hand off verified work before starting fresh.

These are suggestions. Review and run the displayed command yourself; accepting
one does not execute it. Decline/snooze hides it, and “always” remains restricted
to map/trace. A Claude selftest command prepares a preview; execution needs its
existing explicit --run flag. Provider selftests can incur model charges.
