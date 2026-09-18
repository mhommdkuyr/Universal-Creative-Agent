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
            service.liveExecutionOverlay()?.finish(false, "خطأ في UCOA: ${e.message ?: e.javaClass.simpleName}")
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
        service.liveExecutionOverlay()?.start(id, task)
        UcoaDiagnostics.log("REMOTE_BRIDGE", "استلام مهمة سحابية", "id=$id task=${task.take(180)}")
        brain.telemetry("remote_task_received", JSONObject().put("command_id", id))
        val plan = awaitPlan(task, attachments)
        if (!plan.first) {
            service.liveExecutionOverlay()?.finish(false, "فشل بناء الخطة السحابية: ${plan.third ?: "plan failed"}")
            report(id, "failed", JSONObject().put("stage", "plan").put("error", plan.third ?: "plan failed"))
            return
        }
        service.liveExecutionOverlay()?.update(0, 60, "الخطة السحابية", "إرسال القرار إلى UCOA", null, service.foregroundPackageName(), "تم استلام الخطة؛ لن يُعد أي فتح لتطبيق خارجي نجاحًا قبل التحقق.")

        val history = JSONArray(); var completed = false; var lastError = ""; var verifiedSteps = 0
        for (step in 0 until 60) {
            if (!running) return
            brain.telemetry("remote_step_prepare", JSONObject().put("command_id", id).put("step", step))
            service.liveExecutionOverlay()?.update(step + 1, 60, "ملاحظة الشاشة", "التقاط الحالة قبل التنفيذ", null, service.foregroundPackageName(), "UCOA يلتقط UI + screenshot قبل القرار.")
            val beforeUi = safeObserveUi()
            val beforeShot = awaitScreenshot()
            brain.telemetry("remote_step_evidence_ready", JSONObject().put("command_id", id).put("step", step).put("ui_chars", beforeUi.length).put("has_screenshot", !beforeShot.isNullOrBlank()))
            val explicitSettings = taskRequestsSettings(task)
            val currentForeground = service.foregroundPackageName().orEmpty()
            val action: JSONObject
            if (explicitSettings && currentForeground == "com.android.settings") {
                action = JSONObject().apply {
                    put("action", "done")
                    put("done", true)
                    put("message", "UCOA تحقق محليًا من حزمة Android Settings قبل إنهاء المهمة.")
                    put("confidence", 1.0)
                    put("verification_goal", "إثبات أن com.android.settings هي الشاشة الأمامية")
                    put("provider", "local-deterministic-gate")
                    put("output_mode", "local-deterministic-gate")
                }
            } else if (explicitSettings) {
                action = JSONObject().apply {
                    put("action", "open_app_by_name")
                    put("params", JSONObject().put("app_name", "settings"))
                    put("done", false)
                    put("wait_after_ms", 900)
                    put("message", "فتح Android Settings مباشرة من بوابة UCOA المحلية.")
                    put("confidence", 1.0)
                    put("verification_goal", "ظهور com.android.settings مع UI tree وscreenshot")
                    put("provider", "local-deterministic-gate")
                    put("output_mode", "local-deterministic-gate")
                }
            } else {
                val result = awaitStep(task, step, history, beforeUi, beforeShot, attachments)
                if (!result.first || result.second == null) { lastError = result.third ?: "step failed"; break }
                action = result.second!!
            }
            val name = action.optString("action")
            service.liveExecutionOverlay()?.update(step + 1, 60, "قرار Cloud AI", "الأمر المقترح: $name", null, service.foregroundPackageName(), "استدعاء الأمر لا يساوي نجاحًا؛ ستتبع ذلك مراقبة وتحقق.")
            val actionOk = executeAction(action, attachments)
            service.liveExecutionOverlay()?.update(step + 1, 60, "التنفيذ", name, null, service.foregroundPackageName(), if (actionOk) "تم استدعاء الأمر؛ التحقق الآن." else "فشل الاستدعاء قبل التحقق.")
            Thread.sleep(action.optLong("wait_after_ms", 700L).coerceIn(100L, 8000L))
            val afterUi = safeObserveUi()
            val afterShot = awaitScreenshot()
            val verification = awaitVerification(task, action, beforeUi, afterUi, beforeShot, afterShot)
            val verificationRequired = name != "observe"
            val verified = !verificationRequired || verification.first
            if (verificationRequired && verification.first) verifiedSteps += 1
            service.liveExecutionOverlay()?.update(step + 1, 60, "التحقق", name, verified, service.foregroundPackageName(), verification.third ?: "اعتماد حالة الشاشة قبل/بعد التنفيذ.")
            if (!verified && verificationRequired) lastError = verification.third ?: "verification failed"
            UcoaDiagnostics.log("REMOTE_BRIDGE", "تنفيذ أمر سحابي", "id=$id step=$step action=$name ok=$actionOk verified=$verified")
            brain.telemetry("remote_step_done", JSONObject().put("command_id", id).put("step", step).put("action", name).put("action_ok", actionOk).put("verified", verification.first))
            history.put(JSONObject(action.toString()).apply {
                put("ucoa_action_ok", actionOk)
                put("ucoa_verified", verification.first)
                put("ucoa_foreground_package", service.foregroundPackageName().orEmpty())
            })
            if (name == "done" || action.optBoolean("done", false)) {
                completed = actionOk && verified
                if (!completed && lastError.isBlank()) lastError = verification.third ?: "لم يثبت UCOA اكتمال المهمة"
                break
            }
            if (!actionOk && !action.optBoolean("optional", false)) lastError = action.optString("error", "action failed")
        }
        val result = JSONObject().apply {
            put("task", task.take(2000))
            put("steps", history.length())
            put("verified_steps", verifiedSteps)
            put("completion_verified_by_ucoa", completed)
            put("final_foreground", service.foregroundPackageName() ?: "")
            put("evidence_source", "UCOA Accessibility UI tree + screenshot before/after")
            if (lastError.isNotBlank()) put("error", lastError.take(2000))
        }
        service.liveExecutionOverlay()?.finish(completed, if (completed) "اكتمل بعد تحقق UCOA من الحالة النهائية." else (lastError.ifBlank { "لم يثبت اكتمال المهمة." }))
        report(id, if (completed) "completed" else "failed", result)
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

    private fun taskRequestsSettings(task: String): Boolean {
        val t = task.lowercase()
        return t.contains("الإعدادات") ||
            t.contains("اعدادات") ||
            t.contains("الضبط") ||
            t.contains("settings") ||
            t.contains("setting")
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
