from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1] / "activity-android"


class AndroidActivityContractTest(unittest.TestCase):
    def test_manifest_requests_only_usage_stats_special_access(self) -> None:
        manifest = (ROOT / "app/src/main/AndroidManifest.xml").read_text()
        self.assertIn("android.permission.PACKAGE_USAGE_STATS", manifest)
        for forbidden in (
            "android.permission.INTERNET",
            "android.permission.QUERY_ALL_PACKAGES",
            "android.permission.BIND_ACCESSIBILITY_SERVICE",
            "android.permission.SYSTEM_ALERT_WINDOW",
            "android.permission.RECORD_AUDIO",
            "android.permission.CAMERA",
        ):
            self.assertNotIn(forbidden, manifest)

    def test_activitywatch_clone_uses_platform_usage_events_not_a_shadow_database(self) -> None:
        source = (ROOT / "app/src/main/java/ai/zara/activity/AndroidUsageSource.java").read_text()
        self.assertIn("UsageStatsManager", source)
        self.assertIn("queryEvents", source)
        self.assertIn("ACTIVITY_RESUMED", source)
        self.assertIn("SCREEN_NON_INTERACTIVE", source)
        for forbidden in ("SQLite", "RoomDatabase", "Realm", "ContentProvider"):
            self.assertNotIn(forbidden, source)

    def test_actor_has_one_bounded_serial_owner(self) -> None:
        source = (ROOT / "app/src/main/java/ai/zara/activity/ActivityTrackerActor.java").read_text()
        self.assertRegex(source, r"new ThreadPoolExecutor\(\s*1,\s*1,")
        self.assertIn("new ArrayBlockingQueue<>(8)", source)
        self.assertIn("shutdownNow", source)

    def test_usage_access_settings_is_explicit(self) -> None:
        source = (ROOT / "app/src/main/java/ai/zara/activity/ActivityActivity.java").read_text()
        self.assertIn("Settings.ACTION_USAGE_ACCESS_SETTINGS", source)
        self.assertIn("resolveActivity", source)
        self.assertIn("Usage Access is off", source)

    def test_result_and_range_limits_are_source_enforced(self) -> None:
        source = (ROOT / "app/src/main/java/ai/zara/activity/ActivitySessionizer.java").read_text()
        self.assertIn("MAX_RANGE_MS", source)
        self.assertIn("31L * 24L * 60L * 60L * 1000L", source)
        self.assertIn("MAX_RESULT_LIMIT = 100", source)
        self.assertIn(".limit(limit)", source)

    def test_apk_identity_is_stable(self) -> None:
        build = (ROOT / "app/build.gradle.kts").read_text()
        manifest = (ROOT / "app/src/main/AndroidManifest.xml").read_text()
        self.assertIn('applicationId = "ai.zara.activity"', build)
        self.assertIn('versionName = "0.1.0-alpha.1"', build)
        self.assertIn('android:label="Zara Activity"', manifest)


if __name__ == "__main__":
    unittest.main()
