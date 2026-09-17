# Zara Activity

Zara Activity is a standalone Android app inside the `zara-context` plugin family. It provides ActivityWatch-style app-time summaries using Android's own Usage Access history while keeping the privilege out of the base Zara APK.

Package: `ai.zara.activity`

Version: `0.1.0-alpha.1`

Issue: lost-rob0t/zara-plugins#826

## Privacy model

The alpha requests only `android.permission.PACKAGE_USAGE_STATS`. Android exposes that data only after the user explicitly enables Usage Access in system settings.

The app does **not** request Internet, Accessibility, screen capture/overlay, broad package enumeration, microphone, camera, contacts, location, or notification access. It does not create a second activity-history database. `UsageStatsManager` remains the source of truth and every projection is bounded.

This implementation is independent and does not copy ActivityWatch source or assets.

## What it tracks

- foreground application sessions from `ACTIVITY_RESUMED` / `ACTIVITY_PAUSED`;
- screen-interactive intervals from `SCREEN_INTERACTIVE` / `SCREEN_NON_INTERACTIVE`;
- today's total app time and interactive-screen time;
- top applications by observed foreground duration;
- a bounded recent session timeline.

Lifecycle input is sorted and normalized before aggregation. Duplicate resumes do not double-count; app switches close the previous package; screen-off time is excluded; open sessions are clamped to the requested end; ranges are limited to 31 days and result limits to 100.

## Build

The project follows the standalone Zara Companion Android layout and expects JDK 17, Android SDK 36, and Gradle 9.5.1+.

```sh
cd plugins/zara-context/activity-android
gradle --no-daemon :app:assembleDebug :app:lintDebug
```

Run the dependency-free core tests:

```sh
./test/run.sh
```

The debug APK is written to:

```text
app/build/outputs/apk/debug/app-debug.apk
```

## Use

1. Install and launch **Zara Activity**.
2. Tap **Grant Usage Access**.
3. Enable Zara Activity in Android's Usage Access screen.
4. Return to the app. It refreshes automatically and can also be refreshed manually.

If a package label cannot be resolved under Android package visibility rules, Zara Activity displays the package id instead of asking for `QUERY_ALL_PACKAGES`.

## Zara integration boundary

This slice does not invent a competing Android plugin host. Until lost-rob0t/zara#924 is canonical, Zara Activity is a standalone local dashboard. The future typed host vocabulary is reserved as:

```text
activity.status
activity.summary(start_ms, end_ms, limit)
activity.timeline(start_ms, end_ms, limit)
activity.top(start_ms, end_ms, limit)
```

Raw usage history must never be injected into model context automatically. Zara/Prolog policy remains the authority that chooses when a bounded projection is requested.

## Non-goals in alpha.1

- browser URL/history capture;
- Accessibility-based window text capture;
- screenshots or screen recording;
- cloud sync;
- productivity scoring/categories;
- custom long-term archive database;
- arbitrary ActivityWatch server/protocol compatibility;
- desktop tracking.

## Verification

CI builds/lints the APK, runs the pure Java state-machine tests, runs repository source-policy tests, exercises Usage Access on Android emulators, captures permission-required and permission-granted screenshots, and records source/APK SHA-256 receipts. Emulator evidence is not a substitute for physical-device acceptance.

License: GPL-3.0-or-later.
