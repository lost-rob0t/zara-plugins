# Zara Activity Android E2E

## Required evidence

For every release candidate, preserve together:

- exact Git source SHA;
- APK SHA-256;
- pure Java sessionizer/actor test output;
- Android build and lint result;
- emulator API 29 and API 35+ smoke results;
- screenshot with Usage Access denied;
- screenshot after Usage Access is granted and platform usage events have been generated.

A screenshot containing a synthetic/fake fixture must not be presented as proof that `UsageStatsManager` works.

## Emulator smoke

A disposable emulator can grant/revoke the special app-op explicitly:

```sh
adb shell appops set ai.zara.activity GET_USAGE_STATS ignore
adb shell am start -n ai.zara.activity/.ActivityActivity
adb exec-out screencap -p > usage-access-required.png

adb shell appops set ai.zara.activity GET_USAGE_STATS allow
adb shell am start -a android.settings.SETTINGS
sleep 2
adb shell am start -n ai.zara.activity/.ActivityActivity
sleep 2
adb exec-out screencap -p > usage-access-granted.png
```

The smoke runner must also inspect `dumpsys package ai.zara.activity`/`appops` and fail if Usage Access is not in the intended state. It must not grant Accessibility, Internet, overlay, camera, microphone, or package-enumeration privileges.

## Physical device gate

Before a stable release, test on a Samsung daily-driver class device with normal One UI battery management:

- grant/revoke Usage Access;
- background/foreground and process recreation;
- midnight/day rollover;
- screen lock/AOD/unlock;
- split-screen and rapid app switching;
- large font/minimum width;
- 24-hour and 7-day summaries;
- battery impact over a normal day.

No always-on service is required for alpha. The app queries Android's existing usage history on demand.
