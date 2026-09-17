package ai.zara.activity;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

public final class ActivitySessionizer {
    public static final long MAX_RANGE_MS = 31L * 24L * 60L * 60L * 1000L;
    public static final int MAX_RESULT_LIMIT = 100;

    private static final int ACTIVITY_RESUMED = 1;
    private static final int ACTIVITY_PAUSED = 2;
    private static final int SCREEN_INTERACTIVE = 15;
    private static final int SCREEN_NON_INTERACTIVE = 16;

    private ActivitySessionizer() {}

    public static ActivitySummary summarize(
        List<UsageEventRecord> input,
        long startMs,
        long endMs,
        int limit
    ) {
        validateRange(startMs, endMs, limit);
        List<UsageEventRecord> events = new ArrayList<>(input == null ? List.of() : input);
        events.sort(
            Comparator.comparingLong(UsageEventRecord::timestampMs)
                .thenComparingInt(UsageEventRecord::type)
                .thenComparing(UsageEventRecord::packageName)
        );

        State state = new State();
        List<ActivitySession> allSessions = new ArrayList<>();
        long interactiveMs = 0L;
        long cursor = events.isEmpty() ? startMs : Math.min(startMs, events.get(0).timestampMs());

        for (UsageEventRecord event : events) {
            long timestamp = event.timestampMs();
            if (timestamp > endMs) break;
            if (timestamp > cursor) {
                long from = Math.max(cursor, startMs);
                long to = Math.min(timestamp, endMs);
                if (to > from) {
                    if (state.interactive) interactiveMs += to - from;
                    if (state.interactive && state.foregroundPackage != null) {
                        appendSession(allSessions, state.foregroundPackage, from, to);
                    }
                }
            }
            apply(state, event);
            cursor = Math.max(cursor, timestamp);
        }

        if (cursor < endMs) {
            long from = Math.max(cursor, startMs);
            if (endMs > from) {
                if (state.interactive) interactiveMs += endMs - from;
                if (state.interactive && state.foregroundPackage != null) {
                    appendSession(allSessions, state.foregroundPackage, from, endMs);
                }
            }
        }

        long appMs = allSessions.stream().mapToLong(ActivitySession::durationMs).sum();
        long rangeMs = endMs - startMs;
        interactiveMs = Math.min(interactiveMs, rangeMs);
        appMs = Math.min(appMs, rangeMs);

        List<ActivitySession> sessions = allSessions.size() <= limit
            ? List.copyOf(allSessions)
            : List.copyOf(allSessions.subList(allSessions.size() - limit, allSessions.size()));

        Map<String, Long> byPackage = new HashMap<>();
        for (ActivitySession session : allSessions) {
            byPackage.merge(session.packageName(), session.durationMs(), Long::sum);
        }
        List<AppDuration> topApps = byPackage.entrySet().stream()
            .map(entry -> new AppDuration(entry.getKey(), entry.getValue()))
            .sorted(Comparator.comparingLong(AppDuration::durationMs).reversed().thenComparing(AppDuration::packageName))
            .limit(limit)
            .collect(Collectors.toList());

        return new ActivitySummary(startMs, endMs, interactiveMs, appMs, sessions, topApps);
    }

    private static void validateRange(long startMs, long endMs, int limit) {
        if (startMs < 0 || endMs <= startMs) throw new IllegalArgumentException("endMs must be greater than startMs");
        if (endMs - startMs > MAX_RANGE_MS) throw new IllegalArgumentException("range exceeds 31 days");
        if (limit < 1 || limit > MAX_RESULT_LIMIT) throw new IllegalArgumentException("limit must be between 1 and 100");
    }

    private static void apply(State state, UsageEventRecord event) {
        switch (event.type()) {
            case ACTIVITY_RESUMED -> {
                if (!event.packageName().isBlank()) {
                    state.foregroundPackage = event.packageName();
                    if (!state.screenStateKnown) {
                        state.interactive = true;
                        state.screenStateKnown = true;
                    }
                }
            }
            case ACTIVITY_PAUSED -> {
                if (event.packageName().equals(state.foregroundPackage)) state.foregroundPackage = null;
            }
            case SCREEN_INTERACTIVE -> {
                state.interactive = true;
                state.screenStateKnown = true;
            }
            case SCREEN_NON_INTERACTIVE -> {
                state.interactive = false;
                state.screenStateKnown = true;
            }
            default -> {
            }
        }
    }

    private static void appendSession(List<ActivitySession> sessions, String packageName, long startMs, long endMs) {
        if (endMs <= startMs) return;
        if (!sessions.isEmpty()) {
            ActivitySession previous = sessions.get(sessions.size() - 1);
            if (previous.packageName().equals(packageName) && previous.endMs() == startMs) {
                sessions.set(sessions.size() - 1, new ActivitySession(packageName, previous.startMs(), endMs));
                return;
            }
        }
        sessions.add(new ActivitySession(packageName, startMs, endMs));
    }

    private static final class State {
        private String foregroundPackage;
        private boolean interactive;
        private boolean screenStateKnown;
    }
}

final class UsageEventRecord {
    private final long timestampMs;
    private final String packageName;
    private final int type;

    UsageEventRecord(long timestampMs, String packageName, int type) {
        if (timestampMs < 0) throw new IllegalArgumentException("timestampMs must be non-negative");
        this.timestampMs = timestampMs;
        this.packageName = Objects.requireNonNullElse(packageName, "");
        this.type = type;
    }

    long timestampMs() { return timestampMs; }
    String packageName() { return packageName; }
    int type() { return type; }
}

final class ActivitySession {
    private final String packageName;
    private final long startMs;
    private final long endMs;

    ActivitySession(String packageName, long startMs, long endMs) {
        this.packageName = Objects.requireNonNull(packageName, "packageName");
        if (packageName.isBlank()) throw new IllegalArgumentException("packageName must not be blank");
        if (startMs < 0 || endMs <= startMs) throw new IllegalArgumentException("invalid session range");
        this.startMs = startMs;
        this.endMs = endMs;
    }

    String packageName() { return packageName; }
    long startMs() { return startMs; }
    long endMs() { return endMs; }
    long durationMs() { return endMs - startMs; }
}

final class AppDuration {
    private final String packageName;
    private final long durationMs;

    AppDuration(String packageName, long durationMs) {
        this.packageName = Objects.requireNonNull(packageName, "packageName");
        if (packageName.isBlank()) throw new IllegalArgumentException("packageName must not be blank");
        if (durationMs < 0) throw new IllegalArgumentException("durationMs must be non-negative");
        this.durationMs = durationMs;
    }

    String packageName() { return packageName; }
    long durationMs() { return durationMs; }
}

final class ActivitySummary {
    private final long startMs;
    private final long endMs;
    private final long interactiveMs;
    private final long appMs;
    private final List<ActivitySession> sessions;
    private final List<AppDuration> topApps;

    ActivitySummary(
        long startMs,
        long endMs,
        long interactiveMs,
        long appMs,
        List<ActivitySession> sessions,
        List<AppDuration> topApps
    ) {
        this.startMs = startMs;
        this.endMs = endMs;
        this.interactiveMs = interactiveMs;
        this.appMs = appMs;
        this.sessions = List.copyOf(sessions);
        this.topApps = List.copyOf(topApps);
    }

    long startMs() { return startMs; }
    long endMs() { return endMs; }
    long interactiveMs() { return interactiveMs; }
    long appMs() { return appMs; }
    List<ActivitySession> sessions() { return sessions; }
    List<AppDuration> topApps() { return topApps; }
}
