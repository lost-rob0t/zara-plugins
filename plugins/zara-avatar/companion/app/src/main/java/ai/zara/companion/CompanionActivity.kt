package ai.zara.companion

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import kotlinx.coroutines.*
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest

class CompanionActivity : Activity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private lateinit var status: TextView
    private lateinit var importButton: Button
    private var importing = false

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 24, 24, 24)
        }
        column.setOnApplyWindowInsetsListener { view, insets ->
            view.setPadding(24, 24 + insets.systemWindowInsetTop, 24, 24 + insets.systemWindowInsetBottom)
            insets
        }
        setContentView(ScrollView(this).apply { addView(column) })
        column.addView(TextView(this).apply { text = "Zara Companion"; textSize = 24f })
        status = TextView(this).apply { textSize = 15f }
        column.addView(status)
        fun button(label: String, action: () -> Unit): Button = Button(this).also {
            it.text = label
            it.setOnClickListener { action() }
            column.addView(it)
        }
        button("Allow overlay") {
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
        }
        button("Allow status notifications") {
            if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 2)
        }
        importButton = button("Import VRM (maximum 32 MiB)") {
            if (!importing) startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                type = "*/*"; addCategory(Intent.CATEGORY_OPENABLE)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }, 1)
        }
        button("Show companion") { command("show") }
        button("Hide companion") { stopService(Intent(this, OverlayService::class.java)) }
        button("Move avatar: toggle drag / click-through") { command("edit") }
        button("Avatar size: small / medium / large") { command("size") }
        button("Idle / stop dancing and talking") { command("stop") }
        for ((name, label) in listOf("wave" to "Wave", "nod" to "Nod", "shake" to "Shake head",
            "dance_bounce" to "Dance: bounce", "dance_sway" to "Dance: sway", "dance_step" to "Dance: step")) {
            button(label) { command("motion", name) }
        }
        for (name in listOf("neutral", "happy", "sad", "angry", "relaxed", "surprised", "excited")) {
            button("Emotion: $name") { command("emotion", name) }
        }
        button("Talking animation demo (10 seconds; no audio)") { command("speech") }
        column.addView(TextView(this).apply {
            text = "Local controls only in this alpha. Zara host integration is pending #924. " +
                "Screen Vision is a separate plugin. Expressions depend on the imported model."
        })
    }

    override fun onResume() {
        super.onResume()
        status.text = "Overlay: ${if (Settings.canDrawOverlays(this)) "allowed" else "not allowed"}\n" +
            "Avatar: ${if (File(filesDir, "avatar.vrm").isFile) "imported" else "import required"}\n" +
            getSharedPreferences("companion", MODE_PRIVATE).getString("status", "")
    }

    private fun command(action: String, value: String? = null) {
        if (!Settings.canDrawOverlays(this) || !File(filesDir, "avatar.vrm").isFile) {
            Toast.makeText(this, "Allow overlay and import a VRM first.", Toast.LENGTH_SHORT).show(); return
        }
        val intent = Intent(this, OverlayService::class.java).setAction(action).putExtra("value", value)
        try { startForegroundService(intent) }
        catch (_: RuntimeException) { status.text = "Android could not start the overlay. Check permissions and retry." }
    }

    @Deprecated("Platform Activity document result")
    override fun onActivityResult(request: Int, result: Int, data: Intent?) {
        super.onActivityResult(request, result, data)
        val uri = data?.data ?: return
        if (request != 1 || result != RESULT_OK || importing) return
        importing = true; importButton.isEnabled = false
        stopService(Intent(this, OverlayService::class.java))
        scope.launch {
            try {
                val hash = withContext(Dispatchers.IO) {
                    val temp = File.createTempFile("avatar-", ".pending", filesDir)
                    try {
                        val digest = MessageDigest.getInstance("SHA-256")
                        contentResolver.openInputStream(uri).use { input ->
                            requireNotNull(input)
                            FileOutputStream(temp).use { output ->
                                val buffer = ByteArray(32768)
                                var total = 0L
                                while (true) {
                                    ensureActive()
                                    val count = input.read(buffer)
                                    if (count < 0) break
                                    if (count == 0) continue
                                    total += count
                                    require(total <= 32L * 1024 * 1024)
                                    digest.update(buffer, 0, count); output.write(buffer, 0, count)
                                }
                                require(total >= 32)
                                output.fd.sync()
                            }
                        }
                        ensureActive()
                        temp.inputStream().use { input ->
                            val header = ByteArray(12)
                            check(input.read(header) == header.size)
                            val words = java.nio.ByteBuffer.wrap(header).order(java.nio.ByteOrder.LITTLE_ENDIAN)
                            require(words.int == 0x46546c67 && words.int == 2 && words.int.toLong() == temp.length())
                        }
                        android.system.Os.rename(temp.absolutePath, File(filesDir, "avatar.vrm").absolutePath)
                        digest.digest().joinToString("") { "%02x".format(it) }
                    } finally { temp.delete() }
                }
                getSharedPreferences("companion", MODE_PRIVATE).edit().putString("avatar_sha256", hash).apply()
                status.text = "Imported. Tap Show companion to validate and render."
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { status.text = "Import failed. Choose a readable VRM under 32 MiB." }
            finally { importing = false; importButton.isEnabled = true }
        }
    }

    override fun onDestroy() { scope.cancel(); super.onDestroy() }
}
