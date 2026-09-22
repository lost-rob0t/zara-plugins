package ai.zara.companion

import android.app.*
import android.content.*
import android.graphics.Color
import android.graphics.PixelFormat
import android.hardware.input.InputManager
import android.os.*
import android.provider.Settings
import android.view.*
import android.webkit.*
import android.widget.Toast
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.File
import java.io.FileInputStream

class OverlayService : Service() {
    private data class OverlayCommand(val action: String, val value: String?, val bpm: Int)

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val mailbox = Channel<OverlayCommand>(16)
    private var web: WebView? = null
    private var params: WindowManager.LayoutParams? = null
    private var edit = false
    private var size = 1
    private var watching = false
    private val wm by lazy { getSystemService(WindowManager::class.java) }
    private val power by lazy { getSystemService(PowerManager::class.java) }
    private val appOps by lazy { getSystemService(AppOpsManager::class.java) }
    private val prefs by lazy { getSharedPreferences("companion", MODE_PRIVATE) }
    private val thermal = PowerManager.OnThermalStatusChangedListener { updateActive() }
    private val permission = AppOpsManager.OnOpChangedListener { _, _ ->
        scope.launch { if (!Settings.canDrawOverlays(this@OverlayService)) fail("Overlay permission revoked.") }
    }
    private val screen = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) { updateActive() }
    }

    override fun onCreate() {
        super.onCreate()
        val notices = getSystemService(NotificationManager::class.java)
        notices.createNotificationChannel(NotificationChannel("companion", "Zara Companion", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, CompanionActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, OverlayService::class.java).setAction("hide"), PendingIntent.FLAG_IMMUTABLE)
        val notification = Notification.Builder(this, "companion").setSmallIcon(R.drawable.ic_companion)
            .setContentTitle("Zara Companion").setContentText("Avatar overlay. Tap for controls.")
            .setContentIntent(open).setOngoing(true)
            .addAction(Notification.Action.Builder(null, "Stop", stop).build()).build()
        try { startForeground(1, notification) }
        catch (_: RuntimeException) { fail("Foreground service unavailable."); return }
        scope.launch {
            for (command in mailbox) {
                try { execute(command) }
                catch (e: CancellationException) { throw e }
                catch (_: RuntimeException) { fail("Overlay operation failed. Reopen Companion to retry.") }
            }
        }
        val filter = IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_OFF); addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_USER_PRESENT); addAction(PowerManager.ACTION_POWER_SAVE_MODE_CHANGED)
        }
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(screen, filter, Context.RECEIVER_NOT_EXPORTED)
        else registerReceiver(screen, filter)
        power.addThermalStatusListener(mainExecutor, thermal)
        appOps.startWatchingMode(AppOpsManager.OPSTR_SYSTEM_ALERT_WINDOW, packageName, permission)
        watching = true
    }

    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent == null || intent.action == "hide") { stopSelf(); return START_NOT_STICKY }
        if (!Settings.canDrawOverlays(this)) { fail("Overlay permission required."); return START_NOT_STICKY }
        if (intent.action == "stop") {
            if (web == null) { stopSelf(); return START_NOT_STICKY }
            while (mailbox.tryReceive().isSuccess) { }
            js(JSONObject().put("type", "stop"))
        } else {
            val bpm = intent.getIntExtra("bpm", 120)
            if (bpm !in 40..200) {
                prefs.edit().putString("status", "Dance BPM rejected outside 40..200.").apply()
                return START_NOT_STICKY
            }
            val command = OverlayCommand(intent.action ?: "show", intent.getStringExtra("value"), bpm)
            if (!mailbox.trySend(command).isSuccess) {
                Toast.makeText(this, "Companion is busy; command rejected.", Toast.LENGTH_SHORT).show()
            }
        }
        return START_NOT_STICKY
    }

    private fun execute(command: OverlayCommand) {
        val action = command.action
        val value = command.value
        if (web == null) {
            if (action != "show") {
                Toast.makeText(this, "Show Companion first, then choose an animation.", Toast.LENGTH_SHORT).show()
                stopSelf(); return
            }
            show()
        }
        when (action) {
            "show" -> updateActive()
            "motion" -> if (value in listOf("wave", "nod", "shake", "dance_bounce", "dance_sway", "dance_step")) {
                js(JSONObject().put("type", "motion").put("name", value)
                    .put("loop", value!!.startsWith("dance_")).put("bpm", command.bpm))
            }
            "emotion" -> if (value in listOf("neutral", "happy", "sad", "angry", "relaxed", "surprised", "excited")) {
                js(JSONObject().put("type", "emotion").put("name", value))
            }
            "speech" -> js(JSONObject().put("type", "speech").put("active", true))
            "edit" -> { edit = !edit; layout() }
            "size" -> { size = (size + 1) % 3; layout() }
            else -> prefs.edit().putString("status", "Unknown command rejected.").apply()
        }
    }

    @android.annotation.SuppressLint("SetJavaScriptEnabled", "ClickableViewAccessibility")
    private fun show() {
        check(File(filesDir, "avatar.vrm").isFile)
        val view = WebView(this)
        web = view
        view.setBackgroundColor(Color.TRANSPARENT)
        view.settings.apply {
            javaScriptEnabled = true; domStorageEnabled = false
            allowFileAccess = false; allowContentAccess = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            setSupportMultipleWindows(false)
            javaScriptCanOpenWindowsAutomatically = false
            mediaPlaybackRequiresUserGesture = true
            cacheMode = WebSettings.LOAD_NO_CACHE
        }
        view.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                if (message.messageLevel() == ConsoleMessage.MessageLevel.ERROR) {
                    val detail = message.message().take(400)
                    prefs.edit().putString("renderer_console_error", detail).apply()
                    android.util.Log.e("ZaraCompanion", "WebView: $detail")
                }
                return true
            }
        }
        view.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest) = true
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse = resource(request)
            override fun onPageFinished(view: WebView, url: String) { updateActive() }
            override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                fail("Renderer stopped. Reopen Companion."); return true
            }
        }
        params = WindowManager.LayoutParams(1, 1, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
            PixelFormat.TRANSLUCENT).apply { gravity = Gravity.TOP or Gravity.START }
        wm.addView(view, params)
        layout(reset = true)
        var touchX = 0f; var touchY = 0f; var originX = 0; var originY = 0
        view.setOnTouchListener { _, event ->
            if (!edit) false else {
                val p = params!!
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> { touchX = event.rawX; touchY = event.rawY; originX = p.x; originY = p.y }
                    MotionEvent.ACTION_MOVE -> {
                        p.x = originX + (event.rawX - touchX).toInt(); p.y = originY + (event.rawY - touchY).toInt()
                        constrain(); wm.updateViewLayout(view, p)
                    }
                    MotionEvent.ACTION_UP -> prefs.edit().putInt("x", p.x).putInt("y", p.y).apply()
                }
                true
            }
        }
        view.loadUrl("https://companion.zara.invalid/index.html")
        scope.launch {
            val loaded = withTimeoutOrNull(20000) {
                var ready = false
                while (!ready && web === view) {
                    delay(200)
                    ready = suspendCancellableCoroutine { continuation ->
                        view.evaluateJavascript("window.companion && window.companion.ready === true") { result ->
                            if (continuation.isActive) continuation.resumeWith(Result.success(result == "true"))
                        }
                    }
                }
                ready
            }
            if (web === view && loaded != true) fail("Avatar load timed out. Import a supported VRM and retry.")
        }
        prefs.edit().putString("status", "Overlay started; avatar loading is separate from host connection.").apply()
    }

    private fun resource(request: WebResourceRequest): WebResourceResponse {
        fun denied() = WebResourceResponse("text/plain", "UTF-8", 403, "Blocked", emptyMap(), ByteArrayInputStream(ByteArray(0)))
        val uri = request.url
        val path = uri.path ?: return denied()
        if (request.method != "GET" || uri.scheme != "https" || uri.host != "companion.zara.invalid"
            || uri.port != -1 || uri.query != null || path.split('/').any { it == ".." || it == "." }
            || path.contains('\\')) return denied()
        return try {
            if (path == "/avatar.vrm") {
                val file = File(filesDir, "avatar.vrm")
                if (file.length() !in 32..(32L * 1024 * 1024)) return denied()
                WebResourceResponse("model/gltf-binary", null, FileInputStream(file))
            } else {
                val allowed = path in listOf("/index.html", "/scene.mjs", "/motion.mjs", "/model.mjs", "/style.css")
                    || (path.startsWith("/vendor/") && path.endsWith(".js"))
                if (!allowed) return denied()
                val mime = if (path.endsWith(".html")) "text/html" else if (path.endsWith(".css")) "text/css" else "text/javascript"
                WebResourceResponse(mime, "UTF-8", assets.open("companion$path"))
            }
        } catch (_: java.io.IOException) { denied() }
    }

    private fun layout(reset: Boolean = false) {
        val p = params ?: return
        val density = resources.displayMetrics.density
        p.width = (listOf(160, 220, 280)[size] * density).toInt().coerceAtMost(resources.displayMetrics.widthPixels - 32)
        p.height = (p.width * 1.55).toInt().coerceAtMost(resources.displayMetrics.heightPixels - 96)
        if (reset) { p.x = prefs.getInt("x", resources.displayMetrics.widthPixels - p.width - 16); p.y = prefs.getInt("y", resources.displayMetrics.heightPixels - p.height - 96) }
        p.flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            (if (edit) 0 else WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE)
        p.alpha = if (edit) 1f else if (Build.VERSION.SDK_INT >= 31)
            minOf(0.75f, getSystemService(InputManager::class.java).maximumObscuringOpacityForTouch) else 0.75f
        constrain(); wm.updateViewLayout(web, p)
    }
    private fun constrain() {
        val p = params ?: return
        p.x = p.x.coerceIn(0, maxOf(0, resources.displayMetrics.widthPixels - p.width))
        p.y = p.y.coerceIn(24, maxOf(24, resources.displayMetrics.heightPixels - p.height - 48))
    }
    private fun updateActive() {
        val view = web ?: return
        if (!Settings.canDrawOverlays(this)) { fail("Overlay permission revoked."); return }
        val active = power.isInteractive && !getSystemService(KeyguardManager::class.java).isKeyguardLocked
            && power.currentThermalStatus < PowerManager.THERMAL_STATUS_CRITICAL
        val fps = if (power.isPowerSaveMode || power.currentThermalStatus >= PowerManager.THERMAL_STATUS_MODERATE) 15 else 30
        if (active) { view.visibility = View.VISIBLE; view.onResume(); view.resumeTimers() }
        js(JSONObject().put("type", "active").put("value", active), silent = true)
        js(JSONObject().put("type", "quality").put("fps", fps), silent = true)
        if (!active) { view.visibility = View.GONE; view.onPause(); view.pauseTimers() }
    }
    private fun js(command: JSONObject, silent: Boolean = false) {
        web?.evaluateJavascript("window.companion ? window.companion.command($command) : null") { result ->
            if (!silent && (result == "null" || !result.contains("\"ok\":true"))) {
                Toast.makeText(this, "Avatar not ready or command rejected.", Toast.LENGTH_SHORT).show()
            }
        }
    }
    private fun fail(message: String) { prefs.edit().putString("status", message).apply(); stopSelf() }
    override fun onConfigurationChanged(config: android.content.res.Configuration) {
        super.onConfigurationChanged(config); if (web != null) layout()
    }
    override fun onDestroy() {
        mailbox.cancel(); scope.cancel()
        if (watching) { unregisterReceiver(screen); power.removeThermalStatusListener(thermal); appOps.stopWatchingMode(permission) }
        web?.let { view ->
            view.resumeTimers()
            if (view.isAttachedToWindow) wm.removeViewImmediate(view)
            view.stopLoading(); view.destroy()
        }
        web = null; params = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }
}
