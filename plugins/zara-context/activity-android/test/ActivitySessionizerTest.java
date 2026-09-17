package ai.zara.activity;

import java.util.List;

public final class ActivitySessionizerTest {
    private static final int RESUMED = 1;
    private static final int PAUSED = 2;
    private static final int SCREEN_ON = 15;
    private static final int SCREEN_OFF = 16;

    public static void main(String[] args) {
        singleResumePause();
        openSessionClampsToEnd();
        pauseWithoutResumeAddsNothing();
        duplicateResumeDoesNotDoubleCount();
        appSwitchClosesPrevious();
        outOfOrderEventsSortDeterministically();
        screenOffExcludesTime();
        topListIsBoundedAndSorted();
        invalidRangesFailClosed();
        System.out.println("ActivitySessionizerTest PASS");
    }

    private static UsageEventRecord e(long at, String pkg, int type) {
        return new UsageEventRecord(at, pkg, type);
    }

    private static ActivitySummary summarize(List<UsageEventRecord> events, long start, long end, int limit) {
        return ActivitySessionizer.summarize(events, start, end, limit);
    }

    private static void singleResumePause() {
        ActivitySummary s = summarize(List.of(e(100, "a", RESUMED), e(400, "a", PAUSED)), 0, 1000, 10);
        eq(300, s.appMs(), "single app duration");
        eq(1, s.sessions().size(), "single session count");
    }

    private static void openSessionClampsToEnd() {
        ActivitySummary s = summarize(List.of(e(100, "a", RESUMED)), 0, 500, 10);
        eq(400, s.appMs(), "open session clamps to end");
    }

    private static void pauseWithoutResumeAddsNothing() {
        ActivitySummary s = summarize(List.of(e(200, "a", PAUSED)), 0, 500, 10);
        eq(0, s.appMs(), "orphan pause");
    }

    private static void duplicateResumeDoesNotDoubleCount() {
        ActivitySummary s = summarize(List.of(e(100, "a", RESUMED), e(150, "a", RESUMED), e(300, "a", PAUSED)), 0, 500, 10);
        eq(200, s.appMs(), "duplicate resume");
    }

    private static void appSwitchClosesPrevious() {
        ActivitySummary s = summarize(List.of(e(100, "a", RESUMED), e(250, "b", RESUMED), e(500, "b", PAUSED)), 0, 1000, 10);
        eq(400, s.appMs(), "switch total");
        eq(2, s.sessions().size(), "switch sessions");
        eq("a", s.sessions().get(0).packageName(), "first package");
        eq(150, s.sessions().get(0).durationMs(), "first duration");
    }

    private static void outOfOrderEventsSortDeterministically() {
        ActivitySummary s = summarize(List.of(e(500, "a", PAUSED), e(100, "a", RESUMED), e(250, "a", RESUMED)), 0, 1000, 10);
        eq(400, s.appMs(), "sorted events");
    }

    private static void screenOffExcludesTime() {
        ActivitySummary s = summarize(List.of(
            e(0, "", SCREEN_ON), e(100, "a", RESUMED), e(300, "", SCREEN_OFF),
            e(700, "", SCREEN_ON), e(900, "a", PAUSED), e(1000, "", SCREEN_OFF)
        ), 0, 1000, 10);
        eq(400, s.appMs(), "screen-off app exclusion");
        eq(600, s.interactiveMs(), "interactive total");
    }

    private static void topListIsBoundedAndSorted() {
        ActivitySummary s = summarize(List.of(
            e(0, "", SCREEN_ON), e(10, "a", RESUMED), e(110, "a", PAUSED),
            e(120, "b", RESUMED), e(420, "b", PAUSED),
            e(430, "c", RESUMED), e(630, "c", PAUSED)
        ), 0, 1000, 2);
        eq(2, s.topApps().size(), "top limit");
        eq("b", s.topApps().get(0).packageName(), "top package");
        eq(300, s.topApps().get(0).durationMs(), "top duration");
    }

    private static void invalidRangesFailClosed() {
        throwsIllegal(() -> summarize(List.of(), 100, 100, 10), "empty range");
        throwsIllegal(() -> summarize(List.of(), 0, 31L * 24 * 60 * 60 * 1000 + 1, 10), "range > 31 days");
        throwsIllegal(() -> summarize(List.of(), 0, 100, 0), "zero limit");
        throwsIllegal(() -> summarize(List.of(), 0, 100, 101), "limit > 100");
    }

    private static void eq(long expected, long actual, String label) {
        if (expected != actual) throw new AssertionError(label + ": expected=" + expected + " actual=" + actual);
    }

    private static void eq(String expected, String actual, String label) {
        if (!expected.equals(actual)) throw new AssertionError(label + ": expected=" + expected + " actual=" + actual);
    }

    private static void throwsIllegal(Runnable action, String label) {
        try {
            action.run();
            throw new AssertionError(label + ": expected IllegalArgumentException");
        } catch (IllegalArgumentException expected) {
        }
    }
}
