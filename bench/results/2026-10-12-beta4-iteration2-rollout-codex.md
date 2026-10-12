# Beta.4 correction capture, iteration 2 (2026-10-12)

Source `9c962a8`, Codex `gpt-6-luna/high`, original seed base `978207194577267098`. Rollout: workspace **1/5**, Markdown **4/5**, baseline **0/5**. Codex→Codex decisions: workspace **3/3**, baseline **0/3**. Gate **failed**. All 53 calls completed.

| Trial | Workspace | Failed workspace checks | Captured corrected lane / receipt | Brief corrected lane / receipt | Markdown / failed checks | Baseline / failed checks |
|---|---|---|---|---|---|---|
| 1 | pass | none | no / no | no / no | pass / none | abstention / lane, receipt, manifest_attempted |
| 2 | guess_or_incomplete | lane | no / no | no / no | guess_or_incomplete / lane | guess_or_incomplete / lane, receipt, manifest_attempted |
| 3 | guess_or_incomplete | lane | no / no | no / no | pass / none | guess_or_incomplete / lane, receipt |
| 4 | guess_or_incomplete | lane | no / no | no / no | pass / none | guess_or_incomplete / lane, receipt, manifest_attempted |
| 5 | abstention | lane, receipt, manifest_attempted | no / no | no / no | pass / none | guess_or_incomplete / lane, receipt, manifest_attempted |

Before iteration 2: original workspace 2/5, Markdown 5/5, baseline 0/5; iteration 1 workspace 3/5, Markdown 5/5, baseline 0/5. Same seeds, small n and different code revisions do not establish causality. The subject matcher is lexical; arbitrary paraphrases still need an explicit Handoff.

Usage: **5,148,411 input + 83,919 output tokens** (cached input included once). Codeburn pricing is unavailable, not zero. No Claude sessions were run.

Claude review needed: live Claude correction check + Claude->Codex n=3 on 9c962a8aa7752eaac088922e583783deaa1ff375.

The correction is absent from every prepared Captured block and brief. The brief conflict check assumes a captured constraint is newer without checking checkpoint provenance; stale values suppress the saved Next action. The direct prompt-hook regression tests pass, but this resumed headless path still does not persist the correction. Next hypothesis: retain actual prompt/Stop payloads and capture-health records to distinguish hook delivery from transcript freshness. No third iteration or extra benchmark was run; #89 remains draft.
