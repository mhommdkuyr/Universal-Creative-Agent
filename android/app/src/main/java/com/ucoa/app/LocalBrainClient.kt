package com.ucoa.app

import android.content.Context

/**
 * Compatibility facade kept for existing integrations. The production Android
 * client is intentionally cloud-only: no model, provider key, or inference
 * engine is packaged in the APK.
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

    fun isBundled(): Boolean = false

    /**
     * Preserves the old callback contract. Classification now delegates to
     * the cloud planner so behavior is controlled server-side and can change
     * without shipping a new APK.
     */
    fun classify(task: String, apps: List<String>, callback: (Result) -> Unit) {
        AgentBrainClient(context).plan(task, emptyList()) { response ->
            val body = response.body
            val first = body?.optJSONArray("steps")?.optString(0).orEmpty()
            callback(
                if (response.ok && first.isNotBlank()) {
                    Result(false, raw = body?.toString().orEmpty())
                } else {
                    Result(false, raw = body?.toString().orEmpty(), error = response.error ?: "cloud_plan_unavailable")
                }
            )
        }
    }

    fun close() = Unit
}
