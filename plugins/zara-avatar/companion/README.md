# Zara Companion — Android animation alpha

Tracking: zara-plugins #805; host contract: Zara #924; architecture: Zara #923.

**Implemented source, not yet shipping-accepted.** A separate Android app named
**Zara Companion**, package `ai.zara.companion`, version `0.1.0-alpha.1`.
This is an Android consumer of the existing `zara-avatar` renderer dependencies,
not a second Python plugin registry entry. The existing Electron renderer and
published plugin catalog are unchanged.

## Shipping minimum

Animations, emotions and dancing are required, not optional future polish.

| Behavior | This slice |
| --- | --- |
| Idle breathing, blink, subtle head/gaze movement | Procedural; no motion downloads |
| Wave, nod, shake head | Bounded one-shot motions |
| Dance bounce, sway, step | Three original procedural loops; upper and lower body |
| Emotions | Neutral, happy, sad, angry, relaxed, surprised; excited maps to happy |
| Transitions | 250 ms smooth pose transitions; smooth expression changes |
| Talking | Explicit 10-second silent animation demo; bounded aa/ih/ou/ee/oh input in engine |
| Stop | Interrupts queued work, ends dance/demo, closes mouth and blends to idle |
| Overlay | Local show/hide, drag mode, three sizes, saved position, click-through mode |
| Phone lifecycle | Screen/lock suspension, 30/15 FPS quality, critical thermal pause |
| Zara host speech/commands | **Pending #924**; no exported unauthenticated service |

Emotions require the corresponding expressions in the user's VRM. Unsupported
facial presets are not synthesized or claimed as visually working. Actual
audio-driven lip sync remains a host integration gate; the demo generates no
speech and does not listen to the microphone. Dances have no bundled music.

Import your own licensed VRM. No third-party avatar or motion assets are bundled.
VRM 1.0 and VRM 0.x embedded GLB containers are accepted within documented budgets:
32 MiB file, 1 MiB JSON, 1024 nodes, depth 64, 2 million accessor elements,
4096-pixel image sides and 32 million total source texels. External resources,
Draco/meshopt/KTX2 compression and unsupported image formats are rejected in this
first slice. This is a bounded supported subset, not a complete hostile-file
security proof.

## Build

Use JDK 21, Gradle 9.5.1, Android SDK 37 and Build Tools 36.0.0.
The Android Gradle Plugin is pinned to 9.2.0. Renderer packages come from the
existing adjacent `renderer/package-lock.json` with npm integrity checks.
No Electron binary, npm packages or build outputs belong in Git.

```sh
cd plugins/zara-avatar/renderer
npm ci --omit=dev --ignore-scripts
cd ../companion
node --test test/*.test.mjs
python3 -m unittest discover -s test -p 'test_*.py'
gradle --no-daemon :app:assembleDebug :app:lintDebug
```

Output: `app/build/outputs/apk/debug/app-debug.apk`. Install through the normal
Android package installer, or `adb install -r` that exact path on your own device.
The dedicated GitHub Actions workflow also builds a debug APK, captures its source
SHA, and emits dependency/license/hash evidence. It does not publish a signed
release or assert physical-device acceptance.

Nix asset/package integration is still pending; this slice does not claim an
existing Nix renderer package. Native shell compilation and device evidence must
be checked separately from the pure JavaScript/Python tests.

## Use

Open Companion, allow the overlay, import a VRM, and tap **Show companion**.
Then select an emotion or a dance. The avatar uses a small transparent window;
ordinary taps pass through until **Move avatar** enables drag mode. The status
notification opens controls and has an immediate **Stop** action. **Hide** removes
the overlay. There is no boot-started service or automatic capture.

The silent talking-demo button is deliberately labeled as a demo. A real Zara
speech stream should use the engine's viseme messages once #924 supplies its
reviewed, authenticated app-to-app boundary.

## Renderer command contract

The bounded JavaScript motion actor accepts data, never code:

```js
actor.send({ type: 'motion', name: 'dance_step', loop: true, bpm: 130 });
actor.send({ type: 'emotion', name: 'happy', strength: 0.8 });
actor.send({ type: 'visemes', weights: { aa: 0.7, oh: 0.2 } });
actor.send({ type: 'stop' });
```

The Android `Channel` mailbox has 16 entries; the renderer mailbox has 32.
Overflow rejects rather than grows. Stop bypasses the backlog. Visemes expire
within 250 ms without fresh input. There are no microphone, network, Accessibility,
MediaProjection or note permissions. Screen Vision remains a separate plugin.

The service is **non-exported**. These are internal alpha controls, not the
`ZARA-ANDROID-PLUGIN/1` host protocol. Installing this APK does not yet make it
appear as an authorized connected plugin in Zara. Do not add an arbitrary
broadcast, JavaScript bridge, localhost server, or exported Binder shortcut.

## Evidence / remaining release gates

Local RED: the new motion tests failed because `motion.mjs` did not exist.
Local GREEN: 16 JavaScript behavior/model tests and 3 Python packaging tests.
The package tests use explicit fake dependency files, not a real npm install;
no GPU/device/Android build claim follows from them.

Before shipping, require the exact candidate APK build/lint, real VRM rendering
and visual review, #924 integration, real speech-driven visemes, independently
reviewed protocol/privilege decisions, stable signing, and device evidence for
permission revoke, lock/unlock, stop, rotation, tap-through, thermal behavior,
model failure and repeated load/unload memory. Keep #805 open until those pass.

Platform references used:
- https://pixiv.github.io/three-vrm/docs/classes/three-vrm.VRMHumanoid.html
- https://pixiv.github.io/three-vrm/docs/classes/three-vrm.VRMExpressionManager.html
- https://developer.android.com/reference/android/view/WindowManager.LayoutParams
- https://developer.android.com/develop/background-work/services/fgs/service-types
- https://developer.android.com/build/releases/agp-9-2-0-release-notes
