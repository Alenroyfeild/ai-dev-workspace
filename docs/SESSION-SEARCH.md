# Search more clients

`ws sessions search "words"` searches Claude/Codex plus Gemini session JSON and
JSONL under ~/.gemini/tmp, and Cursor JSONL transcripts under ~/.cursor/projects
(including JSONL saved with a .txt extension). To use the directory supplied by
a Cursor hook, run `ws sessions search "words" --root cursor="/path/to/transcripts"`.
Repeat --root for multiple clients; explicit roots replace the default set.

Gemini patches/rewinds are replayed by the capture adapter; removed/old message
text is excluded. New clients return conversation text, excluding tool results
and thoughts. Malformed, unreadable, symlinked and over-50-MB files are skipped.
Results retain date/tool/session_file/snippet, redaction and the 20-hit limit.
Cursor's JSONL shape is the X1 fixture adapter, not a guaranteed public schema;
plain-text exports and editor databases are not supported. Live clients remain
unverified; no sessions are created or modified by search.

Official references: [Cursor hooks and transcript_path](https://cursor.com/docs/hooks),
[Gemini session storage](https://geminicli.com/docs/cli/session-management/),
[Gemini recording formats](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/services/chatRecordingService.ts).
