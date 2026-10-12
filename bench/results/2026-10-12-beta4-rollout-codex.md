# Paired-seed Codex rollout — beta.4 candidate (2026-10-12)

On candidate `756a412`, workspace **3/5**, Markdown **5/5**, baseline **0/5**. Previous kit `c0d7d49` on the same seed base `978207194577267098`: workspace 2/5, Markdown 5/5, baseline 0/5. All 45 current rollout calls completed. The candidate **does not meet the gate** and remains draft.

Two prior workspace failures became passes; one prior pass became a lane failure. This paired-seed comparison is still small and uses different kit revisions; it does not establish that the code caused the net gain.

| Trial (seed_index + 1) | Prior workspace | Current workspace | Failed workspace checks | Baseline failed checks | Markdown |
|---|---|---|---|---|---|
| 1 | pass | guess_or_incomplete | lane | lane, receipt, manifest_attempted | pass |
| 2 | pass | pass | none | lane, receipt | pass |
| 3 | guess_or_incomplete | pass | none | lane, receipt, manifest_attempted | pass |
| 4 | abstention | abstention | lane, receipt, manifest_attempted | lane, receipt, manifest_attempted | pass |
| 5 | guess_or_incomplete | pass | none | lane, receipt, manifest_attempted | pass |

Every prepared workspace Handoff lacks the corrected lane and receipt. Trials 2, 3 and 5 passed with both values present in Next action. Trial 1's Next action shortened the lane to a number; the replacement receipt survived, but the lane check failed. Trial 4 had both values in its brief and abstained; stale Captured constraints still name the original values. Automatic correction capture remains unreliable.

Next hypothesis: preserve the current correction directly from the documented UserPromptSubmit payload before relying on a later transcript read, and protect it from a stale Stop overwrite. Add a failing replay with the real prompt payload and stale transcript before changing code. No further fix or rerun was performed in this batch.

Codex→Codex decisions: workspace **3/3**, baseline **0/3**, all eight calls completed. Claude→Codex cross-check pending (Claude runs it); no Claude sessions were started for this proof.

Usage across both proofs: 53 calls, 5,191,712 input tokens and 81,820 output tokens (cached input is included, not added twice). USD is unavailable, not zero. Raw metrics: [rollout](2026-10-12-beta4-rollout-codex.json), [decisions](2026-10-12-beta4-decisions-codex.json), [per-trial diagnosis](2026-10-12-beta4-proof-summary.json).
