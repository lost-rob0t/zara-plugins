package ai.zara.activity;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.Locale;
import java.util.concurrent.CompletionException;

public final class ActivityActivity extends Activity {
    private static final int SUMMARY_LIMIT = 20;
    private static final int BACKGROUND = Color.rgb(7, 7, 9);
    private static final int FOREGROUND = Color.rgb(242, 242, 247);
    private static final int MUTED = Color.rgb(168, 168, 177);
    private static final int ACCENT = Color.rgb(255, 67, 81);

    private ActivityTrackerActor actor;
    private TextView statusView;
    private TextView totalsView;
    private TextView topAppsView;
    private TextView timelineView;
    private Button grantButton;
    private Button refreshButton;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        actor = new ActivityTrackerActor(new AndroidUsageSource(this));
        setContentView(buildContent());
    }

    @Override
    protected void onResume() {
        super.onResume();
        refresh();
    }

    @Override
    protected void onDestroy() {
        if (actor != null) actor.close();
        super.onDestroy();
    }

    private View buildContent() {
        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(BACKGROUND);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(22), dp(28), dp(22), dp(32));
        scroll.addView(root, new ScrollView.LayoutParams(
            ScrollView.LayoutParams.MATCH_PARENT,
            ScrollView.LayoutParams.WRAP_CONTENT
        ));

        TextView title = text("Zara Activity", 30, FOREGROUND);
        title.setTypeface(title.getTypeface(), Typeface.BOLD);
        root.addView(title);

        TextView subtitle = text("Private app-time tracking from Android Usage Access", 15, MUTED);
        root.addView(subtitle, marginTop(6));

        statusView = text("Checking Usage Access…", 15, MUTED);
        root.addView(statusView, marginTop(22));

        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        actions.setGravity(Gravity.START);
        root.addView(actions, marginTop(12));

        grantButton = button("Grant Usage Access");
        grantButton.setOnClickListener(view -> openUsageAccess());
        actions.addView(grantButton);

        refreshButton = button("Refresh");
        refreshButton.setOnClickListener(view -> refresh());
        LinearLayout.LayoutParams refreshParams = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        );
        refreshParams.leftMargin = dp(10);
        actions.addView(refreshButton, refreshParams);

        root.addView(sectionLabel("TODAY"), marginTop(28));
        totalsView = text("—", 24, FOREGROUND);
        root.addView(totalsView, marginTop(8));

        root.addView(sectionLabel("TOP APPS"), marginTop(28));
        topAppsView = text("—", 16, FOREGROUND);
        topAppsView.setLineSpacing(0f, 1.35f);
        root.addView(topAppsView, marginTop(8));

        root.addView(sectionLabel("RECENT ACTIVITY"), marginTop(28));
        timelineView = text("—", 15, FOREGROUND);
        timelineView.setLineSpacing(0f, 1.35f);
        root.addView(timelineView, marginTop(8));

        TextView footer = text(
            "No cloud sync · no Accessibility · no screen capture · no Internet permission",
            13,
            MUTED
        );
        root.addView(footer, marginTop(30));
        return scroll;
    }

    private void refresh() {
        if (actor == null) return;
        refreshButton.setEnabled(false);
        statusView.setText("Reading local usage history…");
        long endMs = System.currentTimeMillis();
        ZoneId zone = ZoneId.systemDefault();
        long startMs = LocalDate.now(zone).atStartOfDay(zone).toInstant().toEpochMilli();
        actor.refresh(startMs, endMs, SUMMARY_LIMIT).whenComplete((snapshot, error) ->
            runOnUiThread(() -> render(snapshot, error))
        );
    }

    private void render(ActivitySnapshot snapshot, Throwable error) {
        refreshButton.setEnabled(true);
        if (error != null) {
            Throwable cause = error instanceof CompletionException && error.getCause() != null ? error.getCause() : error;
            statusView.setText("Could not read usage history: " + cause.getClass().getSimpleName());
            grantButton.setVisibility(View.VISIBLE);
            clearData();
            return;
        }
        if (snapshot == null || snapshot.status() == ActivitySnapshot.Status.ERROR) {
            statusView.setText("Usage query failed locally.");
            grantButton.setVisibility(View.VISIBLE);
            clearData();
            return;
        }
        if (snapshot.status() == ActivitySnapshot.Status.USAGE_ACCESS_REQUIRED) {
            statusView.setText("Usage Access is off. Android will not expose app-time data until you grant it.");
            grantButton.setVisibility(View.VISIBLE);
            clearData();
            return;
        }

        grantButton.setVisibility(View.GONE);
        statusView.setText("Usage Access on · data stays on this device");
        ActivitySummary summary = snapshot.summary();
        totalsView.setText(
            formatDuration(summary.appMs()) + " app time\n" +
            formatDuration(summary.interactiveMs()) + " screen interactive"
        );
        renderTopApps(summary);
        renderTimeline(summary);
    }

    private void renderTopApps(ActivitySummary summary) {
        if (summary.topApps().isEmpty()) {
            topAppsView.setText("No foreground app activity observed yet.");
            return;
        }
        StringBuilder text = new StringBuilder();
        for (int index = 0; index < summary.topApps().size(); index++) {
            AppDuration item = summary.topApps().get(index);
            if (index > 0) text.append('\n');
            text.append(index + 1)
                .append(". ")
                .append(labelFor(item.packageName()))
                .append("  ·  ")
                .append(formatDuration(item.durationMs()));
        }
        topAppsView.setText(text.toString());
    }

    private void renderTimeline(ActivitySummary summary) {
        if (summary.sessions().isEmpty()) {
            timelineView.setText("No recent sessions in today's observed window.");
            return;
        }
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("HH:mm", Locale.US)
            .withZone(ZoneId.systemDefault());
        StringBuilder text = new StringBuilder();
        for (int index = summary.sessions().size() - 1; index >= 0; index--) {
            ActivitySession session = summary.sessions().get(index);
            if (text.length() > 0) text.append('\n');
            text.append(formatter.format(Instant.ofEpochMilli(session.startMs())))
                .append("–")
                .append(formatter.format(Instant.ofEpochMilli(session.endMs())))
                .append("  ")
                .append(labelFor(session.packageName()))
                .append("  ·  ")
                .append(formatDuration(session.durationMs()));
        }
        timelineView.setText(text.toString());
    }

    private void openUsageAccess() {
        try {
            Intent intent = new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS);
            if (intent.resolveActivity(getPackageManager()) == null) {
                statusView.setText("This Android build does not expose Usage Access settings.");
                return;
            }
            startActivity(intent);
        } catch (ActivityNotFoundException error) {
            statusView.setText("Usage Access settings are unavailable on this device.");
        }
    }

    private String labelFor(String packageName) {
        try {
            PackageManager manager = getPackageManager();
            ApplicationInfo info = manager.getApplicationInfo(packageName, 0);
            CharSequence label = manager.getApplicationLabel(info);
            return label == null || label.length() == 0 ? packageName : label.toString();
        } catch (PackageManager.NameNotFoundException | SecurityException error) {
            return packageName;
        }
    }

    private void clearData() {
        totalsView.setText("—");
        topAppsView.setText("—");
        timelineView.setText("—");
    }

    private TextView sectionLabel(String value) {
        TextView view = text(value, 12, ACCENT);
        view.setLetterSpacing(0.12f);
        return view;
    }

    private TextView text(String value, float sizeSp, int color) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(sizeSp);
        view.setTextColor(color);
        view.setTextIsSelectable(true);
        return view;
    }

    private Button button(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        return button;
    }

    private LinearLayout.LayoutParams marginTop(int dp) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        );
        params.topMargin = dp(dp);
        return params;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private static String formatDuration(long millis) {
        long totalMinutes = Math.max(0L, millis) / 60_000L;
        long hours = totalMinutes / 60L;
        long minutes = totalMinutes % 60L;
        if (hours > 0) return hours + "h " + minutes + "m";
        if (minutes > 0) return minutes + "m";
        return Math.max(0L, millis) / 1000L + "s";
    }
}
