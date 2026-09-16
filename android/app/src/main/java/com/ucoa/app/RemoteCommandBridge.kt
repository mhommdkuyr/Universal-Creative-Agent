package com.ucoa.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

class RemoteCommandBridge(private val context: Context, private val service: UcoaAccessibilityService) {
    @Volatile private var running = false
    private val brain = AgentBrainClient(context)
    private var worker: Thread? = null
    fun start() {
        if (running) return
        running = true
        worker = thread(name = "ucoa-remote-bridge", isDaemon = true) { bootstrapAndLoop() }
    }
    fun stop() { running = false; worker?.interrupt(); worker = null }

    private fun bootstrapAndLoop() {
        val latch = CountDownLatch(1); var ok = false
        brain.bootstrap { r -> ok = r.ok; latch.countDown() }
        latch.await(20, TimeUnit.SECONDS)
        if (!ok) { UcoaDiagnostics.log("REMOTE_BRIDGE", "فشل تهيئة جسر السحابة"); return }
        while (running) {
            try {
                val command = nextCommand() ?: run { Thread.sleep(1500); continue }
                executeCommand(command)
            } catch (e: InterruptedException) { Thread.currentThread().interrupt(); break }
            catch (e: Exception) { UcoaDiagnostics.log("REMOTE_BRIDGE", "خطأ في جسر الأوامر", "${e.javaClass.simpleName}: ${e.message}"); Thread.sleep(2500) }
        }
    }

    private fun nextCommand(): JSONObject? = requestJson("GET", "/v1/client/commands/next", null, 15000).optJSONObject("command")

    private fun executeCommand(command: JSONObject) {
        val id = command.optString("id")
        try {
            executeCommandInternal(command)
        } catch (e: Exception) {
            UcoaDiagnostics.log("REMOTE_BRIDGE", "استثناء أثناء تنفيذ المهمة", "id=$id error=${e.javaClass.simpleName}: ${e.message}")
            report(id, "failed", JSONObject().put("stage", "executor").put("error", e.message ?: e.javaClass.simpleName))
        }
    }

    private fun executeCommandInternal(command: JSONObject) {
        val id = command.optString("id")
        val kind = command.optString("kind")
        val payload = command.optJSONObject("payload") ?: JSONObject()
        if (kind != "task") { report(id, "failed", JSONObject().put("error", "Unsupported command kind: $kind")); return }
        val task = payload.optString("task").trim(); val attachments = list(payload.optJSONArray("attachments"))
        if (task.isBlank()) { report(id, "failed", JSONObject().put("error", "Empty task")); return }
        UcoaDiagnostics.log("REMOTE_BRIDGE", "استلام مهمة سحابية", "id=$id task=${task.take(180)}")
        brain.telemetry("remote_task_received", JSONObject().put("command_id", id))
        val plan = awaitPlan(task, attachments)
        if (!plan.first) { report(id, "failed", JSONObject().put("stage", "plan").put("error", plan.third ?: "plan failed")); return }

        val history = JSONArray(); var completed = false; var lastError = ""
        for (step in 0 until 60) {
            if (!running) return
            brain.telemetry("remote_step_prepare", JSONObject().put("command_id", id).put("step", step))
            val beforeUi = safeObserveUi()
            val beforeShot = awaitScreenshot()
            brain.telemetry("remote_step_evidence_ready", JSONObject().put("command_id", id).put("step", step).put("ui_chars", beforeUi.length).put("has_screenshot", !beforeShot.isNullOrBlank()))
            val result = awaitStep(task, step, history, beforeUi, beforeShot, attachments)
            if (!result.first || result.second == null) { lastError = result.third ?: "step failed"; break }
            val action = result.second!!; history.put(action)
            val name = action.optString("action"); val actionOk = executeAction(action, attachments)
            Thread.sleep(action.optLong("wait_after_ms", 700L).coerceIn(100L, 8000L))
            val afterUi = safeObserveUi()
            val afterShot = awaitScreenshot()
            val verification = awaitVerification(task, action, beforeUi, afterUi, beforeShot, afterShot)
            if (!verification.first && name != "observe") lastError = verification.third ?: "verification failed"
            UcoaDiagnostics.log("REMOTE_BRIDGE", "تنفيذ أمر سحابي", "id=$id step=$step action=$name ok=$actionOk verified=${verification.first}")
            brain.telemetry("remote_step_done", JSONObject().put("command_id", id).put("step", step).put("action", name).put("action_ok", actionOk).put("verified", verification.first))
            if (name == "done" || action.optBoolean("done", false)) { completed = actionOk || action.optBoolean("done", false); break }
            if (!actionOk && !action.optBoolean("optional", false)) lastError = action.optString("error", "action failed")
        }
        report(id, if (completed) "completed" else "failed", JSONObject().apply {
            put("task", task.take(2000)); put("steps", history.length()); put("final_foreground", service.foregroundPackageName() ?: "")
            if (lastError.isNotBlank()) put("error", lastError.take(2000))
        })
    }

    private fun safeObserveUi(timeoutMs: Long = 3000L): String {
        return try {
            val executor = Executors.newSingleThreadExecutor()
            try {
                executor.submit<String> { service.observeUi() }.get(timeoutMs, TimeUnit.MILLISECONDS)
            } finally {
                executor.shutdownNow()
            }
        } catch (e: Exception) {
            UcoaDiagnostics.log("REMOTE_BRIDGE", "تعذر قراءة شجرة الواجهة؛ سيتم المتابعة بدونها", e.javaClass.simpleName)
            "[]"
        }
    }

    private fun executeAction(a: JSONObject, attachments: List<String>): Boolean = when (a.optString("action")) {
        "open_url" -> service.openUrl(a.optString("url"))
        "open_app_by_name" -> service.openAppByName(a.optString("app_name"))
        "click_any_text" -> service.clickAnyText(list(a.optJSONArray("texts")))
        "click_text" -> service.clickText(a.optString("text"))
        "type_into_any" -> service.typeIntoAny(list(a.optJSONArray("hints")), a.optString("text"))
        "type_text" -> service.typeText(a.optString("text"))
        "share_attachment" -> service.shareAttachment(a.optString("uri").ifBlank { attachments.firstOrNull().orEmpty() }, a.optString("package_name").ifBlank { null })
        "tap" -> service.tap(a.optDouble("x").toFloat(), a.optDouble("y").toFloat())
        "long_press" -> service.longPress(a.optDouble("x").toFloat(), a.optDouble("y").toFloat(), a.optLong("duration_ms", 700L))
        "swipe" -> service.swipe(a.optDouble("x1").toFloat(), a.optDouble("y1").toFloat(), a.optDouble("x2").toFloat(), a.optDouble("y2").toFloat(), a.optLong("duration_ms", 500L))
        "back" -> service.back()
        "home" -> service.home()
        "wait", "observe", "done" -> true
        else -> false
    }

    private fun awaitPlan(task: String, attachments: List<String>): Triple<Boolean, JSONObject?, String?> {
        val latch = CountDownLatch(1); var r = AgentBrainClient.Response(false, null, null)
        brain.plan(task, attachments) { x -> r = x; latch.countDown() }; latch.await(190, TimeUnit.SECONDS)
        return Triple(r.ok, r.body, r.error)
    }

    private fun awaitStep(task: String, step: Int, history: JSONArray, ui: String, shot: String?, attachments: List<String>): Triple<Boolean, JSONObject?, String?> {
        val latch = CountDownLatch(1); var r = AgentBrainClient.Response(false, null, null)
        brain.step(task, step, history, ui, shot, service.installedAppLabels(), attachments) { x -> r = x; latch.countDown() }; latch.await(80, TimeUnit.SECONDS)
        return Triple(r.ok, r.body, r.error)
    }

    private fun awaitVerification(task: String, action: JSONObject, beforeUi: String, afterUi: String, beforeScreenshot: String?, afterScreenshot: String?): Triple<Boolean, JSONObject?, String?> {
        val latch = CountDownLatch(1); var r = AgentBrainClient.Response(false, null, null)
        brain.verifyResult(task, action, beforeUi, afterUi, beforeScreenshot, afterScreenshot) { x -> r = x; latch.countDown() }; latch.await(35, TimeUnit.SECONDS)
        return Triple(r.ok, r.body, r.error)
    }

    private fun awaitScreenshot(): String? {
        val latch = CountDownLatch(1); var value: String? = null
        service.captureScreenshotBase64 { x -> value = x; latch.countDown() }
        latch.await(8, TimeUnit.SECONDS)
        return value
    }

    private fun report(id: String, status: String, result: JSONObject) {
        runCatching {
            requestJson("POST", "/v1/client/commands/$id/result", JSONObject().apply {
                put("install_id", installId()); put("status", status); put("result", result)
            }, 15000)
        }.onFailure { e -> UcoaDiagnostics.log("REMOTE_BRIDGE", "فشل إرسال نتيجة المهمة", e.message ?: e.javaClass.simpleName) }
    }

    private fun requestJson(method: String, path: String, body: JSONObject?, timeout: Int): JSONObject {
        val prefs = context.getSharedPreferences("ucoa_brain", Context.MODE_PRIVATE)
        val endpoint = (prefs.getString("endpoint", "https://ucoa-agent-brain.onrender.com") ?: "").trim().trimEnd('/')
        val token = prefs.getString("token", "")?.trim().orEmpty()
        if (endpoint.isBlank() || token.isBlank()) throw IllegalStateException("Cloud session not ready")
        var conn: HttpURLConnection? = null
        try {
            conn = (URL(endpoint + path).openConnection() as HttpURLConnection).apply {
                requestMethod = method; connectTimeout = timeout; readTimeout = timeout; doInput = true
                setRequestProperty("Authorization", "Bearer $token")
                if (body != null) { doOutput = true; setRequestProperty("Content-Type", "application/json") }
            }
            if (body != null) conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode; val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = BufferedReader(InputStreamReader(stream, Charsets.UTF_8)).use { it.readText() }
            if (code !in 200..299) throw IllegalStateException("HTTP $code: ${text.take(1000)}")
            return JSONObject(text)
        } finally { conn?.disconnect() }
    }

    private fun installId(): String = context.getSharedPreferences("ucoa_brain", Context.MODE_PRIVATE).getString("install_id", "")?.trim().orEmpty()
    private fun list(a: JSONArray?): List<String> { if (a == null) return emptyList(); return (0 until a.length()).map { a.optString(it) }.filter { it.isNotBlank() } }
}
