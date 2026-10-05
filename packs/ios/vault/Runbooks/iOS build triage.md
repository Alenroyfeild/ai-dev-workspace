# iOS build triage

1. Capture: `xcodebuild ... 2>&1 | tee build.log` (or export the log from Xcode's Report navigator).
2. Summarise: `ws digest build.log` — distinct problem lines with line numbers. Read those lines in the log, not the whole log.
3. Fix the first real error; later errors are often cascades.
4. CocoaPods: settings in a podspec land in several generated `.xcconfig` files; never hand-edit generated xcconfigs (they are regenerated on `pod install`). Check which `ruby`/`pod` actually runs (`which pod`, `pod --version`).
5. New Xcode or SDK: first check the pod's own changelog/issues for that Xcode version before patching locally; prefer a pod upgrade or a `post_install` hook over editing `Pods/`.
6. Record the fix and the cause in the task record; add a lesson if it could recur.
