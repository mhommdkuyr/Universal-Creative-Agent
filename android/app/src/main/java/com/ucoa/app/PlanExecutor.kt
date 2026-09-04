package com.ucoa.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

class PlanExecutor(private val context: Context) {
    fun firstExecutableAction(taskText: String): JSONArray {
        val command = taskText.lowercase()
        return JSONArray().apply {
            val targetName = when {
                command.contains("capcut") -> "capcut"
                command.contains("canva") -> "canva"
                command.contains("chrome") -> "chrome"
                command.contains("youtube") -> "youtube"
                else -> ""
            }
            if (targetName.isNotEmpty()) {
                val pkg = AppDiscovery.findPackage(context, targetName)
                if (pkg != null) put(JSONObject().apply { put("action", "open_app"); put("package", pkg); put("delay_ms", 250) })
            } else put(JSONObject().apply { put("action", "home"); put("delay_ms", 250) })
        }
    }
}
