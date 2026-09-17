package ai.zara.activity;

import android.app.AppOpsManager;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.os.Process;

import java.util.ArrayList;
import java.util.List;

public final class AndroidUsageSource implements ActivityUsageSource {
    private static final long LOOKBACK_MS = 24L * 60L * 60L * 1000L;

    private final Context context;
    private final UsageStatsManager usageStatsManager;
    private final AppOpsManager appOpsManager;

    public AndroidUsageSource(Context context) {
        this.context = context.getApplicationContext();
        this.usageStatsManager = this.context.getSystemService(UsageStatsManager.class);
        this.appOpsManager = this.context.getSystemService(AppOpsManager.class);
        if (usageStatsManager == null || appOpsManager == null) {
            throw new IllegalStateException("Android usage services are unavailable");
        }
    }

    @Override
    public boolean hasUsageAccess() {
        int mode = appOpsManager.unsafeCheckOpNoThrow(
            AppOpsManager.OPSTR_GET_USAGE_STATS,
            Process.myUid(),
            context.getPackageName()
        );
        return mode == AppOpsManager.MODE_ALLOWED;
    }

    @Override
    public List<UsageEventRecord> query(long startMs, long endMs) {
        if (!hasUsageAccess()) throw new SecurityException("Usage Access is required");
        long queryStart = Math.max(0L, startMs - LOOKBACK_MS);
        UsageEvents events = usageStatsManager.queryEvents(queryStart, endMs);
        List<UsageEventRecord> records = new ArrayList<>();
        if (events == null) return records;

        UsageEvents.Event event = new UsageEvents.Event();
        while (events.hasNextEvent()) {
            events.getNextEvent(event);
            int type = event.getEventType();
            if (type != UsageEvents.Event.ACTIVITY_RESUMED
                && type != UsageEvents.Event.ACTIVITY_PAUSED
                && type != UsageEvents.Event.SCREEN_INTERACTIVE
                && type != UsageEvents.Event.SCREEN_NON_INTERACTIVE) {
                continue;
            }
            String packageName = event.getPackageName();
            records.add(new UsageEventRecord(event.getTimeStamp(), packageName == null ? "" : packageName, type));
        }
        return records;
    }
}
