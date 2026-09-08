package com.ucoa.app

import android.content.Context
import org.json.JSONObject
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * On-device intent brain.
 *
 * The model is packaged into the APK by the Gradle build and copied to
 * internal storage on first use. The model is deliberately only a router:
 * it decides whether a request is a supported local action and returns a
 * strict JSON action. Anything it cannot classify is handed to the cloud brain.
 */
class LocalBrainClient(private val context: Context) {
    data class Result(
        val understood: Boolean,
        val action: String? = null,
        val app: String? = null,
        val confidence: Double = 0.0,
        val raw: String = "",
        val error: String? = null,
    )

    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private var engine: Engine? = null
    private var modelPath: String? = null

    fun isBundled(): Boolean = try {
        context.assets.open(MODEL_ASSET).use { true }
    } catch (_: Exception) {
        false
    }

    fun classify(task: String, apps: List<String>, callback: (Result) -> Unit) {
        executor.execute {
            val result = try {
                if (!isBundled()) {
                    Result(false, raw = "", error = "local_model_asset_missing")
                } else {
                    val e = getEngine()
                    e.createConversation().use { conversation ->
                        val prompt = buildPrompt(task, apps)
                        val response = conversation.sendMessage(prompt)
                        parse(response.toString())
                    }
                }
            } catch (t: Throwable) {
                Result(false, error = "${t.javaClass.simpleName}: ${t.message}")
            }
            callback(result)
        }
    }

    fun close() {
        executor.execute {
            try { engine?.close() } catch (_: Throwable) {}
            engine = null
        }
        executor.shutdown()
    }

    private fun getEngine(): Engine {
        engine?.let { return it }
        val path = ensureModelFile()
        modelPath = path
        val config = EngineConfig(
            modelPath = path,
            backend = Backend.CPU(),
            cacheDir = context.cacheDir.absolutePath,
        )
        return Engine(config).also {
            it.initialize()
            engine = it
        }
    }

    private fun ensureModelFile(): String {
        val target = File(context.filesDir, "ucoa-local-model.litertlm")
        if (!target.exists() || target.length() < MIN_MODEL_BYTES) {
            context.assets.open(MODEL_ASSET).use { input ->
                target.outputStream().use { output -> input.copyTo(output, 1024 * 1024) }
            }
        }
        require(target.length() >= MIN_MODEL_BYTES) { "local_model_incomplete:${target.length()}" }
        return target.absolutePath
    }

    private fun buildPrompt(task: String, apps: List<String>): String {
        val appList = apps.take(80).joinToString(", ")
        return """
            You are the local intent router for an Android automation agent.
            Your job is ONLY to classify requests that can be executed locally.
            Supported local action: open_app.
            If the user asks to open/start/run an installed application, return JSON.
            Otherwise return JSON saying understood=false.
            Never invent an app that is not in the installed-app list.
            Output ONLY valid JSON in this schema:
            {"understood":true,"action":"open_app","app":"exact installed label","confidence":0.99}
            or {"understood":false,"action":null,"app":null,"confidence":0.0}
            Installed apps: $appList
            User request: $task
        """.trimIndent()
    }

    private fun parse(rawResponse: String): Result {
        val raw = rawResponse.trim()
        val start = raw.indexOf('{')
        val end = raw.lastIndexOf('}')
        if (start < 0 || end <= start) return Result(false, raw = raw, error = "local_model_non_json")
        return try {
            val o = JSONObject(raw.substring(start, end + 1))
            val understood = o.optBoolean("understood", false)
            val action = o.optString("action", null)
            val app = o.optString("app", null)
            val confidence = o.optDouble("confidence", 0.0)
            if (understood && action == "open_app" && !app.isNullOrBlank() && confidence >= 0.50) {
                Result(true, action, app, confidence, raw)
            } else {
                Result(false, action = action, app = app, confidence = confidence, raw = raw)
            }
        } catch (t: Throwable) {
            Result(false, raw = raw, error = "local_model_json_error:${t.message}")
        }
    }

    companion object {
        private const val MODEL_ASSET = "ucoa_local_model.litertlm"
        private const val MIN_MODEL_BYTES = 400_000_000L
    }
}
