# iOS Simulator debugging

Drive the Simulator directly instead of asking the user to relay what they see.

- List and boot: `xcrun simctl list devices available`, `xcrun simctl boot "<device>"`.
- Install and launch a built app: `xcrun simctl install booted <App.app>`, `xcrun simctl launch --console booted <bundle-id>`.
- Logs: `xcrun simctl spawn booted log stream --level debug --predicate 'subsystem == "<bundle-id>"' > sim.log`, then `ws digest sim.log`.
- Screenshot for evidence: `xcrun simctl io booted screenshot shot.png`.
- Test on the oldest and newest supported iOS versions before calling a UI fix done; some layout bugs appear only on one OS or one screen width.
- Get the exact on-screen error or log line before diagnosing. Don't let "it broke after X" bias the search toward X.
