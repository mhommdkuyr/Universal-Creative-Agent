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

/** Cloud command bridge. It plans once, executes once, verifies once, then reports the outcome. */
// Live acceptance workflow watches this file to exercise the deployed phone bridge after transport changes.
class RemoteCommandBridge(private val context: Context, private val service: UcoaAccessibilityService) {
    @Volatile private var running = false
    private val brain = AgentBrainClient(context)
    private var worker: Thread? = null
    fun start() { if (running) return; running = true; worker = thread(name = "ucoa-remote-bridge", isDaemon = true) { bootstrapAndLoop() } }
    fun stop() { running = false; worker?.interrupt(); worker = null }
    private fun bootstrapAndLoop() {
        val latch = CountDownLatch(1); var ok = false; brain.bootstrap { r -> ok = r.ok; latch.countDown() }; latch.await(20, TimeUnit.SECONDS)
        if (!ok) { UcoaDiagnostics.log("REMOTE_BRIDGE", "فشل تهيئة جسر السحابة"); return }
        while (running) { try { nextCommand()?.let(::executeCommand) ?: Thread.sleep(1000) } catch (e: InterruptedException) { Thread.currentThread().interrupt(); break } catch (e: Exception) { UcoaDiagnostics.log("REMOTE_BRIDGE", "خطأ في جسر الأوامر", "${e.javaClass.simpleName}: ${e.message}"); Thread.sleep(1800) } }
    }
    private fun nextCommand(): JSONObject? = requestJson("GET", "/v1/client/commands/next", null, 12000).optJSONObject("command")
    private fun executeCommand(command: JSONObject) { val id = command.optString("id"); try { executeCommandInternal(command) } catch (e: Exception) { UcoaDiagnostics.log("REMOTE_BRIDGE", "استثناء أثناء تنفيذ المهمة", "id=$id error=${e.javaClass.simpleName}: ${e.message}"); LiveExecutionState.finish(false, "خطأ في UCOA: ${e.message ?: e.javaClass.simpleName}"); report(id, "failed", json("stage" to "executor", "error" to (e.message ?: e.javaClass.simpleName))) } }

    private fun executeCommandInternal(command: JSONObject) {
        val id = command.optString("id"); val kind = command.optString("kind"); val payload = command.optJSONObject("payload") ?: JSONObject()
        if (kind != "task") { report(id, "failed", json("error" to "Unsupported command kind: $kind")); return }
        val task = payload.optString("task").trim(); val attachments = list(payload.optJSONArray("attachments")); if (task.isBlank()) { report(id, "failed", json("error" to "Empty task")); return }
        LiveExecutionState.begin(task); UcoaDiagnostics.log("REMOTE_BRIDGE", "استلام مهمة سحابية", "id=$id task=${task.take(180)}"); brain.telemetry("remote_task_received", json("command_id" to id))
        val settingsOnly = taskRequestsSettings(task)
        val plan = if (settingsOnly) Triple(true, JSONObject(), null) else awaitPlan(task, attachments)
        if (!plan.first) { LiveExecutionState.finish(false, "فشل بناء الخطة السحابية: ${plan.third ?: "plan failed"}"); report(id, "failed", json("stage" to "plan", "error" to (plan.third ?: "plan failed"))); return }
        if (settingsOnly) LiveExecutionState.update(task, "خطة محلية آمنة", "فتح الإعدادات لا يحتاج إلى مزود AI", 0, 24, null)
        else LiveExecutionState.update(task, "الخطة السحابية", "الخطة معتمدة للتنفيذ", 0, 24, null)
        val history = JSONArray(); var completed = false; var lastError = ""; var verifiedSteps = 0; var lastFingerprint = ""
        for (step in 0 until 24) {
            if (!running) return
            val beforeUi = safeObserveUi(); val beforeShot = awaitScreenshot(); LiveExecutionState.update(task, "ملاحظة الشاشة", "التقاط الحالة قبل التنفيذ", step + 1, 24, null, beforeShot, screenWidth(), screenHeight()); brain.telemetry("remote_step_evidence_ready", json("command_id" to id, "step" to step, "ui_chars" to beforeUi.length, "has_screenshot" to !beforeShot.isNullOrBlank()))
            val action: JSONObject = if (settingsOnly && service.foregroundPackageName() == "com.android.settings") json("action" to "done", "done" to true, "message" to "تم إثبات Android Settings بالفعل.", "confidence" to 1.0, "provider" to "local-deterministic-gate") else if (settingsOnly) json("action" to "open_app_by_name", "params" to json("app_name" to "settings"), "done" to false, "wait_after_ms" to 800, "message" to "فتح Android Settings.", "confidence" to 1.0, "provider" to "local-deterministic-gate") else { val result = awaitStep(task, step, history, beforeUi, beforeShot, attachments); if (!result.first || result.second == null) { lastError = result.third ?: "step failed"; break }; result.second!! }
            val name = action.optString("action"); val fingerprint = action.toString(); if (fingerprint == lastFingerprint && name !in listOf("observe", "wait")) { lastError = "منع تكرار الأمر نفسه دون تغير في الحالة"; break }; lastFingerprint = fingerprint
            LiveExecutionState.update(task, "قرار Cloud AI", name, step + 1, 24, null, beforeShot, screenWidth(), screenHeight(), actionTapX(action), actionTapY(action)); val actionOk = executeAction(action, attachments); Thread.sleep(action.optLong("wait_after_ms", 550L).coerceIn(100L, 5000L)); val afterUi = safeObserveUi(); val afterShot = awaitScreenshot()
            val verification = awaitVerification(task, action, beforeUi, afterUi, beforeShot, afterShot); val verificationRequired = name != "observe"; val verified = !verificationRequired || verification.first; if (verificationRequired && verification.first) verifiedSteps++; LiveExecutionState.update(task, "التنفيذ والتحقق", name, step + 1, 24, verified, afterShot, screenWidth(), screenHeight(), actionTapX(action), actionTapY(action)); if (!verified && verificationRequired) { lastError = verification.third ?: "verification failed"; UcoaDiagnostics.log("REMOTE_BRIDGE", "فشل التحقق بعد التنفيذ؛ أوقف المهمة دون تكرار الأمر", "id=$id step=$step action=$name reason=$lastError") }
            val targetConfirmedByUcoa = actionOk && verificationRequired && verification.first && taskRequestsSettings(task) && service.foregroundPackageName() == "com.android.settings" && afterUi.isNotBlank() && afterUi != "[]" && !afterShot.isNullOrBlank(); if (targetConfirmedByUcoa) { completed = true; lastError = ""; LiveExecutionState.update(task, "نجاح مؤكد من UCOA", "Android Settings", step + 1, 24, true, afterShot, screenWidth(), screenHeight(), actionTapX(action), actionTapY(action)) }
            history.put(json("action" to name, "ucoa_action_ok" to actionOk, "ucoa_verified" to verified, "ucoa_foreground_package" to service.foregroundPackageName().orEmpty())); UcoaDiagnostics.log("REMOTE_BRIDGE", "تنفيذ أمر سحابي", "id=$id step=$step action=$name ok=$actionOk verified=$verified targetConfirmed=$targetConfirmedByUcoa"); brain.telemetry("remote_step_done", json("command_id" to id, "step" to step, "action" to name, "action_ok" to actionOk, "verified" to verified))
            if (completed || name == "done" || action.optBoolean("done", false) || (verificationRequired && !verified)) { completed = completed || (actionOk && verified && (!taskRequestsSettings(task) || targetConfirmedByUcoa)); if (!completed && lastError.isBlank()) lastError = verification.third ?: "لم يثبت UCOA اكتمال الهدف النهائي"; break }; if (!actionOk && !action.optBoolean("optional", false)) { lastError = action.optString("error", "action failed"); break }
        }
        val result = json("task" to task.take(2000), "steps" to history.length(), "verified_steps" to verifiedSteps, "completion_verified_by_ucoa" to completed, "final_foreground" to (service.foregroundPackageName() ?: ""), "evidence_source" to "UCOA Accessibility UI tree + screenshot before/after"); if (lastError.isNotBlank()) result.put("error", lastError.take(2000)); LiveExecutionState.finish(completed, if (completed) "اكتمل بعد تحقق UCOA من الحالة النهائية." else lastError.ifBlank { "لم يثبت اكتمال المهمة." }); report(id, if (completed) "completed" else "failed", result)
    }

    private fun executeAction(a: JSONObject, attachments: List<String>): Boolean {
        // The cloud planner contract nests arguments under "params". Read nested arguments first,
        // while retaining top-level fallback for older plans and test fixtures.
        val p = a.optJSONObject("params") ?: JSONObject()
        fun argString(key: String, default: String = ""): String =
            if (p.has(key)) p.optString(key, default) else a.optString(key, default)
        fun argDouble(key: String, default: Double = 0.0): Double =
            if (p.has(key)) p.optDouble(key, default) else a.optDouble(key, default)
        fun argLong(key: String, default: Long): Long =
            if (p.has(key)) p.optLong(key, default) else a.optLong(key, default)
        fun argArray(key: String): JSONArray? = p.optJSONArray(key) ?: a.optJSONArray(key)

        return when (a.optString("action")) {
            "open_url" -> service.openUrl(argString("url"))
            "open_app_by_name" -> service.openAppByName(argString("app_name"))
            "click_any_text" -> service.clickAnyText(list(argArray("texts")))
            "click_text" -> service.clickText(argString("text"))
            "type_into_any" -> service.typeIntoAny(list(argArray("hints")), argString("text"))
            "type_text" -> service.typeText(argString("text"))
            "share_attachment" -> service.shareAttachment(
                argString("uri").ifBlank { attachments.firstOrNull().orEmpty() },
                argString("package_name").ifBlank { null }
            )
            "tap" -> service.tap(argDouble("x").toFloat(), argDouble("y").toFloat())
            "long_press" -> service.longPress(argDouble("x").toFloat(), argDouble("y").toFloat(), argLong("duration_ms", 700L))
            "swipe" -> service.swipe(
                argDouble("x1").toFloat(), argDouble("y1").toFloat(),
                argDouble("x2").toFloat(), argDouble("y2").toFloat(),
                argLong("duration_ms", 500L)
            )
            "back" -> service.back()
            "home" -> service.home()
            "wait", "observe", "done" -> true
            else -> false
        }
    }

    private fun awaitPlan(task: String, attachments: List<String>): Triple<Boolean, JSONObject?, String?> { val latch = CountDownLatch(1); var r = AgentBrainClient.Response(false, null, null); brain.plan(task, attachments) { x -> r = x; latch.countDown() }; latch.await(190, TimeUnit.SECONDS); return Triple(r.ok, r.body, r.error) }
    private fun awaitStep(task: String, step: Int, history: JSONArray, ui: String, shot: String?, attachments: List<String>): Triple<Boolean, JSONObject?, String?> { val latch = CountDownLatch(1); var r = AgentBrainClient.Response(false, null, null); brain.step(task, step, history, ui, shot, service.installedAppLabels(), attachments) { x -> r = x; latch.countDown() }; latch.await(80, TimeUnit.SECONDS); return Triple(r.ok, r.body, r.error) }
    private fun awaitVerification(task: String, action: JSONObject, beforeUi: String, afterUi: String, beforeScreenshot: String?, afterScreenshot: String?): Triple<Boolean, JSONObject?, String?> {
        val latch = CountDownLatch(1)
        var r = AgentBrainClient.Response(false, null, null)
        brain.verifyResult(task, action, beforeUi, afterUi, beforeScreenshot, afterScreenshot) { x -> r = x; latch.countDown() }
        latch.await(35, TimeUnit.SECONDS)
        // HTTP 200 only means the verifier endpoint responded. A step passes only when
        // the actual nested verifier result explicitly returns verified=true.
        val verifierResult = r.body?.optJSONObject("result") ?: r.body
        val verified = r.ok && verifierResult?.optBoolean("verified", false) == true
        val error = when {
            !r.ok -> r.error
            verified -> null
            else -> verifierResult?.optString("reason")?.takeIf { it.isNotBlank() }
                ?: verifierResult?.optJSONArray("reasons")?.let { reasons ->
                    (0 until reasons.length()).joinToString(", ") { reasons.optString(it) }.ifBlank { null }
                }
                ?: "خادم التحقق لم يؤكد نجاح الخطوة"
        }
        return Triple(verified, verifierResult, error)
    }
    private fun awaitScreenshot(): String? { val latch = CountDownLatch(1); var value: String? = null; service.captureScreenshotBase64 { x -> value = x; latch.countDown() }; latch.await(8, TimeUnit.SECONDS); return value }
    private fun safeObserveUi(): String = runCatching { service.observeUi(320) }.getOrDefault("[]")
    private fun screenWidth(): Int = context.resources.displayMetrics.widthPixels
    private fun screenHeight(): Int = context.resources.displayMetrics.heightPixels
    private fun actionTapX(a: JSONObject): Float? = if (a.optString("action") == "tap" || a.optString("action") == "long_press") a.optDouble("x", Double.NaN).takeUnless { it.isNaN() }?.toFloat() else null
    private fun actionTapY(a: JSONObject): Float? = if (a.optString("action") == "tap" || a.optString("action") == "long_press") a.optDouble("y", Double.NaN).takeUnless { it.isNaN() }?.toFloat() else null
    private fun taskRequestsSettings(task: String): Boolean { val t = task.lowercase(); return t.contains("الإعدادات") || t.contains("اعدادات") || t.contains("الضبط") || t.contains("settings") || t.contains("setting") }
    private fun report(id: String, status: String, result: JSONObject) { runCatching { requestJson("POST", "/v1/client/commands/$id/result", json("install_id" to installId(), "status" to status, "result" to result), 15000) }.onFailure { UcoaDiagnostics.log("REMOTE_BRIDGE", "فشل إرسال نتيجة المهمة", it.message ?: it.javaClass.simpleName) } }
    private fun requestJson(method: String, path: String, body: JSONObject?, timeout: Int, authRetry: Boolean = true): JSONObject {
        val endpoint = brain.endpoint().trim().trimEnd('/')
        val token = brain.token()
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
            if (code == 401 && authRetry) {
                brain.resetSession()
                val latch = CountDownLatch(1)
                var refresh = AgentBrainClient.Response(false, null, "No session response")
                brain.bootstrap { result -> refresh = result; latch.countDown() }
                val finished = latch.await(25, TimeUnit.SECONDS)
                if (!finished || !refresh.ok) {
                    throw IllegalStateException("Cloud session renewal failed: ${refresh.error ?: "timeout"}")
                }
                return requestJson(method, path, body, timeout, false)
            }
            if (code !in 200..299) throw IllegalStateException("HTTP $code: ${text.take(1000)}")
            return JSONObject(text)
        } finally {
            conn?.disconnect()
        }
    }
    private fun installId(): String = context.getSharedPreferences("ucoa_brain", Context.MODE_PRIVATE).getString("install_id", "")?.trim().orEmpty()
    private fun list(a: JSONArray?): List<String> = if (a == null) emptyList() else (0 until a.length()).map { a.optString(it) }.filter { it.isNotBlank() }
    private fun json(vararg pairs: Pair<String, Any?>): JSONObject = JSONObject().apply { pairs.forEach { (k, v) -> put(k, v) } }
}
