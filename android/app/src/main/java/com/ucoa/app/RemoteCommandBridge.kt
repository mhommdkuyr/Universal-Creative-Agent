package com.ucoa.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * Secure cloud-to-device bridge. The server never receives Android UI-control
 * credentials; the installed client session token authorizes only its own queue.
 */
class RemoteCommandBridge(
    private val context: Context,
    private val service: UcoaAccessibilityService
) {
    @Volatile private var running = false
    private val brain = AgentBrainClient(context)
    private var worker: Thread? = null

    fun start() {
        if (running) return
        running = true
        worker = thread(name = "ucoa-remote-bridge", isDaemon = true) {
            bootstrapAndLoop()
        }
    }

    fun stop() {
        running = false
        worker?.interrupt()
        worker = null
    }

    private fun bootstrapAndLoop() {
        val latch = CountDownLatch(1)
        var bootstrapOk = false
        brain.bootstrap { response ->
            bootstrapOk = response.ok
            latch.countDown()
        }
        latch.await(20, TimeUnit.SECONDS)
        if (!bootstrapOk) {
            UcoaDiagnostics.log("REMOTE_BRIDGE", "فشل تهيئة جسر السحابة")
            return
        }

        while (running) {
            try {
                val command = nextCommand() ?: run {
                    Thread.sleep(1500)
                    continue
                }
                executeCommand(command)
            } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
                break
            } catch (e: Exception) {
                UcoaDiagnostics.log("REMOTE_BRIDGE", "خطأ في جسر الأوامر", "${e.javaClass.simpleName}: ${e.message}")
                Thread.sleep(2500)
            }
        }
    }

    private fun nextCommand(): JSONObject? {
        val body = requestJson("GET", "/v1/client/commands/next", null, 15000)
        return body.optJSONObject("command")
    }

    private fun executeCommand(command: JSONObject) {
        val id = command.optString("id")
        val kind = command.optString("kind")
        val payload = command.optJSONObject("payload") ?: JSONObject()
        if (kind != "task") {
            report(id, "failed", JSONObject().put("error", "Unsupported command kind: $kind"))
            return
        }
        val task = payload.optString("task").trim()
        val attachments = jsonStringList(payload.optJSONArray("attachments"))
        if (task.isBlank()) {
            report(id, "failed", JSONObject().put("error", "Empty task"))
            return
        }

        UcoaDiagnostics.log("REMOTE_BRIDGE", "استلام مهمة سحابية", "id=$id task=${task.take(180)}")
        val plan = awaitPlan(task, attachments)
        if (!plan.first || plan.second == null) {
            report(id, "failed", JSONObject().put("stage", "plan").put("error", plan.third ?: "plan failed"))
            return
        }

        val maxSteps = 60
        val history = JSONArray()
        var completed = false
        var lastError = ""

        for (step in 0 until maxSteps) {
            if (!running) return
            val beforeUi = service.observeUi()
            val beforeShot = awaitScreenshot()
            val result = awaitStep(task, step, history, beforeUi, beforeShot, attachments)
            if (!result.first || result.second == null) {
                lastError = result.third ?: "step failed"
                break
            }
            val action = result.second!!
            history.put(action)
            val actionName = action.optString("action")
            val ok = executeAction(action, attachments)
            val waitMs = action.optLong("wait_after_ms", 700L).coerceIn(100L, 8000L)
            if (waitMs > 0) Thread.sleep(waitMs)

            val afterUi = service.observeUi()
            val afterShot = awaitScreenshot()
            val verification = awaitVerification(task, action, beforeUi, afterUi, beforeShot, afterShot)
            if (!verification.first && actionName != "observe") {
                lastError = verification.third ?: "verification failed"
            }

            UcoaDiagnostics.log("REMOTE_BRIDGE", "تنفيذ أمر سحابي", "id=$id step=$step action=$actionName ok=$ok verified=${verification.first}")

            if (actionName == "done" || action.optBoolean("done", false)) {
                completed = ok || action.optBoolean("done", false)
                break
            }
            if (!ok && !action.optBoolean("optional", false)) {
                lastError = action.optString("error", "action failed")
            }
        }

        val status = if (completed) "completed" else "failed"
        report(id, status, JSONObject().apply {
            put("task", task.take(2000))
            put("steps", history.length())
            put("final_foreground", service.foregroundPackageName() ?: "")
            if (lastError.isNotBlank()) put("error", lastError.take(2000))
        })
    }

    private fun executeAction(action: JSONObject, attachments: List<String>): Boolean {
        return when (action.optString("action")) {
            "open_url" -> service.openUrl(action.optString("url"))
            "open_app_by_name" -> service.openAppByName(action.optString("app_name"))
            "click_any_text" -> service.clickAnyText(jsonStringList(action.optJSONArray("texts")))
            "click_text" -> service.clickText(action.optString("text"))
            "type_into_any" -> service.typeIntoAny(jsonStringList(action.optJSONArray("hints")), action.optString("text"))
            "type_text" -> service.typeText(action.optString("text"))
            "share_attachment" -> {
                val uri = action.optString("uri").ifBlank { attachments.firstOrNull().orEmpty() }
                service.shareAttachment(uri, action.optString("package_name").ifBlank { null })
            }
            "tap" -> service.tap(action.optDouble("x").toFloat(), action.optDouble("y").toFloat())
            "long_press" -> service.longPress(action.optDouble("x").toFloat(), action.optDouble("y").toFloat(), action.optLong("duration_ms", 700L))
            "swipe" -> service.swipe(action.optDouble("x1").toFloat(), action.optDouble("y1").toFloat(), action.optDouble("x2").toFloat(), action.optDouble("y2").toFloat(), action.optLong("duration_ms", 500L))
            "back" -> service.back()
            "home" -> service.home()
            "wait", "observe", "done" -> true
            else -> false
        }
    }

    private fun awaitPlan(task: String, attachments: List<String>): Triple<Boolean, JSONObject?, String?> {
        val latch = CountDownLatch(1)
        var result = AgentBrainClient.Response(false, null, null)
        brain.plan(task, attachments) { response -> result = response; latch.countDown() }
        latch.await(190, TimeUnit.SECONDS)
        return Triple(result.ok, result.body, result.error)
    }

    private fun awaitStep(
        task: String,
        step: Int,
        history: JSONArray,
        uiTree: String,
        screenshot: String?,
        attachments: List<String>
    ): Triple<Boolean, JSONObject?, String?> {
        val latch = CountDownLatch(1)
        var result = AgentBrainClient.Response(false, null, null)
        brain.step(task, step, history, uiTree, screenshot, service.installedAppLabels(), attachments) { response -> result = response; latch.countDown() }
        latch.await(80, TimeUnit.SECONDS)
        return Triple(result.ok, result.body, result.error)
    }

    private fun awaitVerification(task: String, action: JSONObject, beforeUi: String, afterUi: String, beforeShot: String?, afterShot: String?): Triple<Boolean, JSONObject?, String?> {
        val latch = CountDownLatch(1)
        var result = AgentBrainClient.Response(false, null, null)
        brain.verifyResult(task, action, beforeUi, afterUi, beforeShot, afterShot) { response -> result = response; latch.countDown() }
        latch.await(35, TimeUnit.SECONDS)
        return Triple(result.ok, result.body, result.error)
    }

    private fun awaitScreenshot(): String? {
        val latch = CountDownLatch(1)
        var value: String? = null
        service.captureScreenshotBase64 { shot -> value = shot; latch.countDown() }
        latch.await(8, TimeUnit.SECONDS)
        return value
    }

    private fun report(id: String, status: String, result: JSONObject) {
        runCatching {
            requestJson(
                "POST",
                "/v1/client/commands/$id/result",
                JSONObject().apply {
                    put("install_id", installId())
                    put("status", status)
                    put("result", result)
                },
                15000
            )
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
                requestMethod = method
                connectTimeout = timeout
                readTimeout = timeout
                doInput = true
                setRequestProperty("Authorization", "Bearer $token")
                if (body != null) {
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                }
            }
            if (body != null) conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = BufferedReader(InputStreamReader(stream, Charsets.UTF_8)).use { it.readText() }
            if (code !in 200..299) throw IllegalStateException("HTTP $code: ${text.take(1000)}")
            return JSONObject(text)
        } finally {
            conn?.disconnect()
        }
    }

    private fun installId(): String {
        val prefs = context.getSharedPreferences("ucoa_brain", Context.MODE_PRIVATE)
        return prefs.getString("install_id", "")?.trim().orEmpty()
    }

    private fun jsonStringList(array: JSONArray?): List<String> {
        if (array == null) return emptyList()
        val values = mutableListOf<String>()
        for (i in 0 until array.length()) values += array.optString(i)
        return values.filter { it.isNotBlank() }
    }
}
