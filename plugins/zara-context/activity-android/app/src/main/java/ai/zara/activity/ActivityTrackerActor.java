package ai.zara.activity;

import java.util.List;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

public final class ActivityTrackerActor implements AutoCloseable {
    private final ActivityUsageSource source;
    private final ThreadPoolExecutor executor;

    public ActivityTrackerActor(ActivityUsageSource source) {
        this.source = source;
        this.executor = new ThreadPoolExecutor(
            1,
            1,
            0L,
            TimeUnit.MILLISECONDS,
            new ArrayBlockingQueue<>(8),
            runnable -> {
                Thread thread = new Thread(runnable, "zara-activity-tracker");
                thread.setDaemon(true);
                return thread;
            },
            new ThreadPoolExecutor.AbortPolicy()
        );
    }

    public CompletableFuture<ActivitySnapshot> refresh(long startMs, long endMs, int limit) {
        try {
            return CompletableFuture.supplyAsync(() -> load(startMs, endMs, limit), executor);
        } catch (RejectedExecutionException error) {
            return CompletableFuture.completedFuture(ActivitySnapshot.error("activity_tracker_busy"));
        }
    }

    private ActivitySnapshot load(long startMs, long endMs, int limit) {
        if (!source.hasUsageAccess()) return ActivitySnapshot.usageAccessRequired();
        try {
            List<UsageEventRecord> events = source.query(startMs, endMs);
            return ActivitySnapshot.ready(ActivitySessionizer.summarize(events, startMs, endMs, limit));
        } catch (SecurityException error) {
            return ActivitySnapshot.usageAccessRequired();
        } catch (RuntimeException error) {
            return ActivitySnapshot.error("activity_query_failed");
        }
    }

    @Override
    public void close() {
        executor.shutdownNow();
    }
}

interface ActivityUsageSource {
    boolean hasUsageAccess();
    List<UsageEventRecord> query(long startMs, long endMs);
}

final class ActivitySnapshot {
    enum Status {
        READY,
        USAGE_ACCESS_REQUIRED,
        ERROR
    }

    private final Status status;
    private final ActivitySummary summary;
    private final String message;

    private ActivitySnapshot(Status status, ActivitySummary summary, String message) {
        this.status = status;
        this.summary = summary;
        this.message = message;
    }

    static ActivitySnapshot ready(ActivitySummary summary) {
        return new ActivitySnapshot(Status.READY, summary, "ready");
    }

    static ActivitySnapshot usageAccessRequired() {
        return new ActivitySnapshot(Status.USAGE_ACCESS_REQUIRED, null, "usage_access_required");
    }

    static ActivitySnapshot error(String message) {
        return new ActivitySnapshot(Status.ERROR, null, message == null || message.isBlank() ? "activity_query_failed" : message);
    }

    Status status() { return status; }
    ActivitySummary summary() { return summary; }
    String message() { return message; }
}
