# Zara Companion changelog

## 0.1.0-alpha.3

- Adds bounded on-device dance preference learning keyed by music genre and tempo band.
- Feeds the selected BPM into the existing procedural bounce, sway, and step motions.
- Adds local Like/Skip teaching controls without microphone, playback capture, notification-listener, network, or MediaProjection permissions.
- Removes import-map dependence from the packaged renderer so the API 29 WebView path can resolve pinned local modules.
- Makes Android overlay E2E wait for asynchronous WindowManager flag publication instead of racing click-through transitions.
- Tests the exact pull-request head, runs the Kotlin dance-policy tests, and gates a signed rolling `companion-android-latest` prerelease on a fully green main build.

## 0.1.0-alpha.2

- Bundled the original CC0 Zara Test Bot VRM and added real-loader, pixel-renderer, and API 29/35 overlay E2E gates.
- Added built-in emotions, gestures, bounce/sway/step dances, transitions, stop, and the silent talking demo.
