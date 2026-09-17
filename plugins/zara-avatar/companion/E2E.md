# Companion E2E and default VRM fixture

## Candidate and scope

PR #809 adds the default fixture and E2E gates to Companion `0.1.0-alpha.2`.
The old alpha.1 APK was built from `19027a3820922e11c213ba24ff65c39d18eab5e3`;
its passing build does not prove this newer candidate passes. Use the exact
current Actions head, APK, `SOURCE_SHA.txt`, and SHA-256 receipt together.

There are three distinct evidence layers:

- Unit/package tests and real-loader/rig/morph checks: no GPU or Android execution.
- Browser pixel checks against the actual APK assets using software WebGL2.
- Android emulator UI, bundled-model selection, SAF import and overlay-window checks.

Physical-device/OEM behavior and Zara #924 authenticated host/Prolog integration
remain separate gates. Do not call a non-exported locally controlled Companion
app a complete Zara-to-Companion integration. Screen Vision remains separate.

## Try the candidate

1. Install the exact alpha.2 debug APK through Android's installer.
2. Open Companion and use **Allow overlay** to grant the Android overlay setting.
3. Tap **Use bundled test bot**, then **Show companion**.
4. Try the emotions, gestures and three dances. Use **Idle / stop dancing and talking**
   or **Hide companion** to stop. No music or real speech is bundled.
5. Use **Import VRM (maximum 32 MiB)** to test another model.

The earlier alpha.1 APK requires manual VRM import. Do not uninstall an existing
app blindly if an upgrade fails: debug signing compatibility is a separate gate.

## Default model

Generate the original CC0-1.0 fixture offline from the Companion directory:

```sh
python3 tools/make_test_vrm.py /tmp/Zara-Test-Bot.vrm
```

Expected SHA-256:

```text
8a4d475dbbd4c59b919a4ae1ee2789d9628276be26318d5d6ae64ec0cf96a0d4
```

The 54,832-byte VRM 1.0 contains humanoid bones, geometric robot meshes and real
happy/sad/angry/relaxed/surprised/blink/viseme morphs. It has no external resources,
borrowed character mesh, textures, animation clips or music. Gradle generates the
same bytes as `assets/default-avatar.vrm`; the generator and generated geometry
are dedicated under CC0-1.0. This is test content, not production character art.

## Real APK loader and pixel tests

Loader integration needs Node 22 and Python's standard library:

```sh
python3 e2e/run_loader.py --apk /path/to/zara-companion-debug.apk \
  --model /tmp/Zara-Test-Bot.vrm --report evidence/loader.json
```

The runner extracts the actual APK dependency files, verifies their receipt,
loads the real VRM, drives the rig and expression morphs, and tests stop/pause,
viseme expiration and malformed input. A passing result is not GPU evidence.

Pixel rendering needs an installed WebGL2-capable Chromium:

```sh
python3 -m pip install playwright==1.57.0 Pillow==12.3.0
python3 -m playwright install --with-deps chromium
CHROMIUM=$(python3 -c 'from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()')
python3 e2e/render_smoke.py --apk /path/to/zara-companion-debug.apk \
  --model /tmp/Zara-Test-Bot.vrm --output evidence/renderer --chromium "$CHROMIUM"
```

The pixel gate uses the APK's renderer at its intercepted virtual HTTPS origin,
a deterministic frame clock, nonblank/transparent pixel checks, every emotion
and dance/gesture, stop, pause/resume, invalid model rejection and external-request
detection. Missing Chromium/WebGL2 and blocked navigation must fail, not skip.
The optional `--source-web` is diagnostic only; CI does not use a source override.

## Android UI and overlay smoke

Use a dedicated unlocked English-language emulator or prepared test device.
This runner replaces the selected avatar, installs only with `--install`, and
never clears app data or uninstalls an application. Explicit test-device consent
is required. Do not use a daily profile containing unsaved work.

```sh
python3 e2e/android_smoke.py --serial emulator-5554 \
  --apk /path/to/zara-companion-debug.apk --model /tmp/Zara-Test-Bot.vrm \
  --output evidence/android --install --emulator --test-device-consent
```

On a physical phone omit `--emulator`, use its authorized ADB serial, and grant
overlay access yourself in Android Settings. Emulator-only AppOps setup is guarded
by `ro.kernel.qemu=1`; it is not proof of the product's permission-consent UI.

The runner checks the installed APK hash, loads the bundled model using its real
button and verifies imported bytes, imports through the real document picker,
checks a real `APPLICATION_OVERLAY` and non-touchable/edit flags, drives local
emotion/dance/gesture buttons, opens Settings underneath, hides/recreates the
overlay, and revokes overlay access on the emulator. It records screenshots.
Timeouts, absent controls/windows, denied permissions and crashes fail the job.
A live window is not proof of correct rendered pixels; review screenshots.

## CI and merge gates

`.github/workflows/companion-android.yml` builds/lints the APK first, then runs
`renderer-e2e` and `android-overlay-e2e` (API 29 and 35). `companion-gate` succeeds
only when all three jobs succeeded; cancellation, missing or skipped work cannot
be treated as green. Each job uploads its evidence, including on failure.
The ordinary repository/Nix/plugin checks remain required independently.

Do not weaken a failure because an emulator's WebView is old. Record the actual
incompatibility and fix the supported runtime/test setup explicitly.

Release acceptance additionally needs independent review, cross-UID touch-through,
rotation, lock/unlock, renderer restarts, thermal/battery and repeated-load resource
evidence on physical hardware, stable signing, and the #924 host/speech path.
Keep feature #805 open until its full acceptance criteria are demonstrated.
