package com.ucoa.app

import android.content.Context
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/** Network transport for the universal agent brain. No model/vendor is hard-coded here. */
class AgentBrainClient(private val context: Context) {
    data class Response(val ok: Boolean, val body: JSONObject?, val error: String? = null)
    private val executor = Executors.newSingleThreadExecutor()
    private val prefs get() = context.getSharedPreferences("ucoa_brain", Context.MODE_PRIVATE)

    fun configured(): Boolean = endpoint().isNotBlank()
    fun endpoint(): String = prefs.getString("endpoint", "")?.trim().orEmpty().trimEnd('/')
    fun token(): String = prefs.getString("token", "")?.trim().orEmpty()
    fun saveConfig(endpoint: String, token: String) { prefs.edit().putString("endpoint", endpoint.trim().trimEnd('/')).putString("token", token.trim()).apply() }

    fun plan(task: String, attachments: List<String>, callback: (Response) -> Unit) {
        val payload = JSONObject().apply {
            put("task", task); put("attachments", JSONArray(attachments))
            put("device", JSONObject().apply { put("manufacturer", Build.MANUFACTURER); put("model", Build.MODEL); put("android", Build.VERSION.SDK_INT) })
        }
        post("/v1/agent/plan", payload, callback)
    }

    fun step(task: String, step: Int, history: JSONArray, uiTree: String, screenshotBase64: String?, installedApps: List<String>, attachments: List<String>, callback: (Response) -> Unit) {
        val payload = JSONObject().apply {
            put("task", task); put("step", step); put("max_steps", 60); put("history", history); put("ui_tree", uiTree)
            if (!screenshotBase64.isNullOrBlank()) put("screenshot_base64", screenshotBase64)
            put("installed_apps", JSONArray(installedApps.take(250)))
            put("attachments", JSONArray(attachments.take(20)))
            put("capabilities", JSONArray(listOf("open_url", "open_app_by_name", "click_any_text", "type_into_any", "share_attachment", "tap", "long_press", "swipe", "back", "home", "wait", "observe", "done")))
        }
        post("/v1/agent/step", payload, callback)
    }

    private fun post(path: String, payload: JSONObject, callback: (Response) -> Unit) {
        val base = endpoint()
        if (base.isBlank()) { callback(Response(false, null, "لم يتم إعداد عنوان عقل AI بعد")); return }
        executor.execute {
            var conn: HttpURLConnection? = null
            try {
                conn = (URL(base + path).openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"; connectTimeout = 12000; readTimeout = 60000; doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                    token().takeIf { it.isNotBlank() }?.let { setRequestProperty("Authorization", "Bearer $it") }
                }
                conn.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
                val code = conn.responseCode; val stream = if (code in 200..299) conn.inputStream else conn.errorStream
                val text = BufferedReader(InputStreamReader(stream, Charsets.UTF_8)).use { it.readText() }
                callback(Response(code in 200..299, runCatching { JSONObject(text) }.getOrNull(), if (code in 200..299) null else "HTTP $code: $text"))
            } catch (e: Exception) { callback(Response(false, null, e.message ?: e.javaClass.simpleName)) }
            finally { conn?.disconnect() }
        }
    }
}
