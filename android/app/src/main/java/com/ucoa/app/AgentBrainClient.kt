package com.ucoa.app

import android.content.Context
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import java.util.concurrent.Executors

/** Network transport for the universal agent brain. Providers and models remain replaceable. */
class AgentBrainClient(private val context: Context) {
    data class Response(val ok: Boolean, val body: JSONObject?, val error: String? = null)
    private val executor = Executors.newSingleThreadExecutor()
    private val prefs get() = context.getSharedPreferences("ucoa_brain", Context.MODE_PRIVATE)
    private val defaultEndpoint = "https://ucoa-agent-brain-local2.onrender.com"

    fun configured(): Boolean = endpoint().isNotBlank()
    fun endpoint(): String = prefs.getString("endpoint", defaultEndpoint)?.trim().orEmpty().trimEnd('/')
    fun token(): String = prefs.getString("token", "")?.trim().orEmpty()
    fun sessionId(): String {
        val current = prefs.getString("session_id", null)
        if (!current.isNullOrBlank()) return current
        val created = UUID.randomUUID().toString().replace("-", "")
        prefs.edit().putString("session_id", created).apply()
        return created
    }
    fun resetSession() { prefs.edit().remove("session_id").apply() }
    fun saveConfig(endpoint: String, token: String) { prefs.edit().putString("endpoint", endpoint.trim().trimEnd('/')).putString("token", token.trim()).apply() }

    fun health(callback: (Boolean, String) -> Unit) {
        val base = endpoint(); if (base.isBlank()) { callback(false, "عنوان العقل غير مُعد"); return }
        executor.execute {
            try {
                val body = requestJson("GET", base + "/health", null, 15000)
                val vision = body.optString("vision_model", "غير متاح")
                callback(true, if (body.optBoolean("brain_configured", false)) "العقل متصل: ${body.optString("model", "local")} | الرؤية: $vision" else "الخادم متصل لكن النموذج غير مهيأ")
            } catch (e: Exception) { callback(false, e.message ?: e.javaClass.simpleName) }
        }
    }

    fun plan(task: String, attachments: List<String>, callback: (Response) -> Unit) {
        val payload = JSONObject().apply {
            put("task", task); put("attachments", JSONArray(attachments)); put("session_id", sessionId())
            put("device", JSONObject().apply { put("manufacturer", Build.MANUFACTURER); put("model", Build.MODEL); put("android", Build.VERSION.SDK_INT) })
        }
        submitJob("/v1/agent/plan", payload, callback)
    }

    fun step(task: String, step: Int, history: JSONArray, uiTree: String, screenshotBase64: String?, installedApps: List<String>, attachments: List<String>, approvedRisks: Boolean = false, callback: (Response) -> Unit) {
        val payload = JSONObject().apply {
            put("task", task); put("step", step); put("max_steps", 60); put("history", history); put("ui_tree", uiTree)
            put("session_id", sessionId()); put("approved_risks", approvedRisks)
            if (!screenshotBase64.isNullOrBlank()) put("screenshot_base64", screenshotBase64)
            put("installed_apps", JSONArray(installedApps.take(250))); put("attachments", JSONArray(attachments.take(20)))
            put("capabilities", JSONArray(listOf("open_url", "open_app_by_name", "click_any_text", "type_into_any", "share_attachment", "tap", "long_press", "swipe", "back", "home", "wait", "observe", "done")))
        }
        submitJob("/v1/agent/step", payload, callback)
    }

    private fun submitJob(path: String, payload: JSONObject, callback: (Response) -> Unit) {
        val base = endpoint(); if (base.isBlank()) { callback(Response(false, null, "لم يتم إعداد عنوان عقل AI بعد")); return }
        executor.execute {
            try {
                val submitted = requestJson("POST", base + path, payload, 20000)
                val jobId = submitted.optString("job_id").takeIf { it.isNotBlank() }
                    ?: throw IllegalStateException("Brain did not return a job_id")
                pollJob(base, jobId, callback, 0)
            } catch (e: Exception) { callback(Response(false, null, e.message ?: e.javaClass.simpleName)) }
        }
    }

    private fun pollJob(base: String, jobId: String, callback: (Response) -> Unit, attempt: Int) {
        if (attempt >= 160) { callback(Response(false, null, "انتهت مهلة انتظار عقل AI")); return }
        try {
            val job = requestJson("GET", base + "/v1/agent/jobs/$jobId", null, 15000)
            when (job.optString("status")) {
                "completed" -> {
                    val result = job.optJSONObject("result")
                    callback(if (result != null) Response(true, result) else Response(false, null, "العقل أنهى المهمة بلا نتيجة"))
                }
                "failed" -> callback(Response(false, null, job.optString("error", "فشل تشغيل عقل AI")))
                else -> {
                    Thread.sleep(1000)
                    pollJob(base, jobId, callback, attempt + 1)
                }
            }
        } catch (e: Exception) { callback(Response(false, null, e.message ?: e.javaClass.simpleName)) }
    }

    private fun requestJson(method: String, url: String, payload: JSONObject?, timeout: Int): JSONObject {
        var conn: HttpURLConnection? = null
        try {
            conn = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = method; connectTimeout = timeout; readTimeout = timeout; doInput = true
                if (payload != null) { doOutput = true; setRequestProperty("Content-Type", "application/json") }
                token().takeIf { it.isNotBlank() }?.let { setRequestProperty("Authorization", "Bearer $it") }
            }
            if (payload != null) conn.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = BufferedReader(InputStreamReader(stream, Charsets.UTF_8)).use { it.readText() }
            if (code !in 200..299) throw IllegalStateException("HTTP $code: $text")
            return JSONObject(text)
        } finally { conn?.disconnect() }
    }
}
