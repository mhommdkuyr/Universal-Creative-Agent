package com.ucoa.app

import android.content.Context
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.ConversationConfig
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.SamplerConfig
import org.json.JSONObject
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/** On-device intent router. Unknown requests are delegated to Cloud Brain. */
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

    fun isBundled(): Boolean = try {
        context.assets.open(MODEL_ASSET).use { true }
    } catch (_: Exception) { false }

    fun classify(task: String, apps: List<String>, callback: (Result) -> Unit) {
        executor.execute {
            val result = try {
                if (!isBundled()) Result(false, error = "local_model_asset_missing")
                else {
                    val e = getEngine()
                    e.createConversation(
                        ConversationConfig(
                            samplerConfig = SamplerConfig(topK = 20, topP = 0.90, temperature = 0.10),
                            systemInstruction = com.google.ai.edge.litertlm.Contents.of(
                                "Return only JSON. You are a fast Android local intent router. Supported action: open_app. If the request is not a simple installed-app launch, return understood=false."
                            ),
                        )
                    ).use { conversation ->
                        val response = conversation.sendMessage(buildPrompt(task, apps))
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
        try { engine?.close() } catch (_: Throwable) {}
        engine = null
        executor.shutdownNow()
    }

    private fun getEngine(): Engine {
        engine?.let { return it }
        val path = ensureModelFile()
        val config = EngineConfig(
            modelPath = path,
            backend = Backend.CPU(threadCount = 4),
            maxNumTokens = 128,
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
        // Keep the prompt tiny: local routing must be fast on phone CPU.
        val appList = apps.take(35).joinToString(", ")
        return "Request: $task\nInstalled apps: $appList\nReturn ONLY JSON: {\"understood\":true,\"action\":\"open_app\",\"app\":\"exact label\",\"confidence\":0.99} OR {\"understood\":false,\"action\":null,\"app\":null,\"confidence\":0.0}"
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
            } else Result(false, action, app, confidence, raw)
        } catch (t: Throwable) {
            Result(false, raw = raw, error = "local_model_json_error:${t.message}")
        }
    }

    companion object {
        private const val MODEL_ASSET = "ucoa_local_model.litertlm"
        private const val MIN_MODEL_BYTES = 300_000_000L
    }
}
