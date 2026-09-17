#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
javac -d "$out" \
  "$root/app/src/main/java/ai/zara/activity/ActivitySessionizer.java" \
  "$root/app/src/main/java/ai/zara/activity/ActivityTrackerActor.java" \
  "$root/test/ActivitySessionizerTest.java" \
  "$root/test/ActivityTrackerActorTest.java"
java -cp "$out" ai.zara.activity.ActivitySessionizerTest
java -cp "$out" ai.zara.activity.ActivityTrackerActorTest
