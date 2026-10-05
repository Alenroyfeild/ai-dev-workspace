
## iOS pack
- Don't run xcodebuild, Simulator install/launch, Fastlane or signing tools unless the user asks; never run Fastlane setup/release lanes as diagnostics (signing recovery can revoke certificates).
- "Needed on iOS?": Android or web behavior is not proof; check the iOS source and the config it reads.
- Gate risky changes with a server/remote flag or an app/OS version check so older builds keep today's behavior.
- Build failures: save the log, `ws digest <log>`, then read only the cited lines. Runbooks: [[Runbooks/iOS build triage]], [[Runbooks/iOS Simulator debugging]], [[Runbooks/App Store review replies]].
