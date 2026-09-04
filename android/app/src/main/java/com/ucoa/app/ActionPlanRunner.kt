package com.ucoa.app

import android.os.Handler
import android.os.Looper
import org.json.JSONArray

class ActionPlanRunner {
    private val handler = Handler(Looper.getMainLooper())

    fun run(json: String, onEvent: (String) -> Unit) {
        val actions = JSONArray(json)
        var delay = 0L
        for (i in 0 until actions.length()) {
            val a = actions.getJSONObject(i)
            val action = a.optString("action")
            val stepDelay = a.optLong("delay_ms", 500L).coerceAtLeast(50L)
            delay += stepDelay
            handler.postDelayed({
                val service = UcoaAccessibilityService.instance
                if (service == null) {
                    onEvent("ERROR: Accessibility Service غير مفعّل")
                    return@postDelayed
                }
                val ok = when (action) {
                    "tap" -> service.tap(a.optDouble("x").toFloat(), a.optDouble("y").toFloat())
                    "long_press" -> service.longPress(a.optDouble("x").toFloat(), a.optDouble("y").toFloat(), a.optLong("duration_ms", 700L))
                    "swipe" -> service.swipe(a.optDouble("x1").toFloat(), a.optDouble("y1").toFloat(), a.optDouble("x2").toFloat(), a.optDouble("y2").toFloat(), a.optLong("duration_ms", 500L))
                    "click_text" -> service.clickText(a.optString("text"))
                    "type_text" -> service.typeText(a.optString("text"))
                    "back" -> service.back()
                    "home" -> service.home()
                    "open_app" -> {
                        val pkg = a.optString("package")
                        if (pkg.isNotBlank()) service.openApp(pkg)
                        else service.openAppByName(a.optString("app_name"))
                    }
                    "observe" -> { onEvent(service.observeUi()); true }
                    else -> false
                }
                onEvent("$action: ${if (ok) "OK" else "FAILED"}")
            }, delay)
        }
    }
}
