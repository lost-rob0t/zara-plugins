#!/usr/bin/env bash
set -euo pipefail
apk=${1:?apk path required}
out=${2:?evidence directory required}
package=ai.zara.activity
activity="$package/.ActivityActivity"
mkdir -p "$out"
adb install -r "$apk"

adb shell appops set "$package" GET_USAGE_STATS ignore
adb shell am force-stop "$package"
adb shell am start -W -n "$activity" >/dev/null
sleep 1
adb shell uiautomator dump /sdcard/activity.xml >/dev/null
adb pull /sdcard/activity.xml "$out/usage-access-required.xml" >/dev/null
grep -q 'Usage Access is off' "$out/usage-access-required.xml"
adb exec-out screencap -p > "$out/usage-access-required.png"

adb shell appops set "$package" GET_USAGE_STATS allow
adb shell am force-stop "$package"
adb shell am start -W -a android.settings.SETTINGS >/dev/null
sleep 2
adb shell am start -W -n "$activity" >/dev/null
sleep 2
adb shell uiautomator dump /sdcard/activity.xml >/dev/null
adb pull /sdcard/activity.xml "$out/usage-access-granted.xml" >/dev/null
grep -q 'Usage Access on' "$out/usage-access-granted.xml"
grep -q 'app time' "$out/usage-access-granted.xml"
adb exec-out screencap -p > "$out/usage-access-granted.png"

adb shell appops get "$package" GET_USAGE_STATS > "$out/appops.txt"
adb shell dumpsys package "$package" > "$out/package.txt"
sha256sum "$apk" > "$out/APK_SHA256.txt"
