package ai.zara.activity;

import java.util.List;
import java.util.concurrent.TimeUnit;

public final class ActivityTrackerActorTest {
    public static void main(String[] args) throws Exception {
        deniedIsTyped();
        revokedDuringQueryIsTyped();
        readySummaryIsBounded();
        System.out.println("ActivityTrackerActorTest PASS");
    }

    private static void deniedIsTyped() throws Exception {
        try (ActivityTrackerActor actor = new ActivityTrackerActor(new FakeSource(false, false))) {
            ActivitySnapshot snapshot = actor.refresh(0, 1000, 10).get(2, TimeUnit.SECONDS);
            eq(ActivitySnapshot.Status.USAGE_ACCESS_REQUIRED, snapshot.status(), "denied status");
        }
    }

    private static void revokedDuringQueryIsTyped() throws Exception {
        try (ActivityTrackerActor actor = new ActivityTrackerActor(new FakeSource(true, true))) {
            ActivitySnapshot snapshot = actor.refresh(0, 1000, 10).get(2, TimeUnit.SECONDS);
            eq(ActivitySnapshot.Status.USAGE_ACCESS_REQUIRED, snapshot.status(), "revoked status");
        }
    }

    private static void readySummaryIsBounded() throws Exception {
        try (ActivityTrackerActor actor = new ActivityTrackerActor(new FakeSource(true, false))) {
            ActivitySnapshot snapshot = actor.refresh(0, 1000, 10).get(2, TimeUnit.SECONDS);
            eq(ActivitySnapshot.Status.READY, snapshot.status(), "ready status");
            if (snapshot.summary() == null || snapshot.summary().appMs() != 400) {
                throw new AssertionError("ready summary duration");
            }
        }
    }

    private static void eq(Object expected, Object actual, String label) {
        if (!expected.equals(actual)) throw new AssertionError(label + ": expected=" + expected + " actual=" + actual);
    }

    private static final class FakeSource implements ActivityUsageSource {
        private final boolean access;
        private final boolean revokeOnQuery;

        private FakeSource(boolean access, boolean revokeOnQuery) {
            this.access = access;
            this.revokeOnQuery = revokeOnQuery;
        }

        @Override
        public boolean hasUsageAccess() {
            return access;
        }

        @Override
        public List<UsageEventRecord> query(long startMs, long endMs) {
            if (revokeOnQuery) throw new SecurityException("revoked");
            return List.of(new UsageEventRecord(100, "a", 1), new UsageEventRecord(500, "a", 2));
        }
    }
}
