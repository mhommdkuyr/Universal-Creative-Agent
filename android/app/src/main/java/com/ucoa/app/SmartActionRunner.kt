package com.ucoa.app

import android.os.Handler
import android.os.Looper
import org.json.JSONArray
import org.json.JSONObject

/** Sequential executor with semantic controls and explicit observation events. */
class SmartActionRunner {
    private val handler = Handler(Looper.getMainLooper())

    fun run(actions: JSONArray, onEvent: (String) -> Unit, onFinished: () -> Unit = {}) {
        var delay = 0L
        for (i in 0 until actions.length()) {
            val action = actions.getJSONObject(i)
            delay += action.optLong("delay_ms", 600L).coerceAtLeast(80L)
            handler.postDelayed({ execute(action, onEvent) }, delay)
        }
        handler.postDelayed(onFinished, delay + 250L)
    }

    private fun execute(a: JSONObject, onEvent: (String) -> Unit) {
        val service = UcoaAccessibilityService.instance ?: run {
            onEvent("العقل: فشل التنفيذ — خدمة الوصول غير مفعلة")
            return
        }
        val action = a.optString("action")
        val optional = a.optBoolean("optional", false)
        val ok = when (action) {
            "open_url" -> service.openUrl(a.optString("url"))
            "open_app_by_name" -> service.openAppByName(a.optString("app_name"))
            "click_any_text" -> service.clickAnyText(list(a.optJSONArray("texts")))
            "type_into_any" -> service.typeIntoAny(list(a.optJSONArray("hints")), a.optString("text"))
            "observe" -> { onEvent("العقل: راقبت واجهة الهدف: ${service.observeUi()}"); true }
            "tap" -> service.tap(a.optDouble("x").toFloat(), a.optDouble("y").toFloat())
            "long_press" -> service.longPress(a.optDouble("x").toFloat(), a.optDouble("y").toFloat(), a.optLong("duration_ms", 700))
            "swipe" -> service.swipe(a.optDouble("x1").toFloat(), a.optDouble("y1").toFloat(), a.optDouble("x2").toFloat(), a.optDouble("y2").toFloat(), a.optLong("duration_ms", 500))
            else -> false
        }
        val result = when { ok -> "تم"; optional -> "تجاوزتها لأنها اختيارية"; else -> "فشل" }
        onEvent("العقل: $action — $result")
    }

    private fun list(values: JSONArray?): List<String> = buildList {
        if (values != null) for (i in 0 until values.length()) add(values.optString(i))
    }
}
