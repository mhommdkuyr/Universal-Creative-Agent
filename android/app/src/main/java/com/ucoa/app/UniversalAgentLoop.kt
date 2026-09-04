package com.ucoa.app

import android.os.Handler
import android.os.Looper
import org.json.JSONArray
import org.json.JSONObject

/** Generic observe -> think -> act -> observe loop. It does not contain app-specific flows. */
class UniversalAgentLoop(private val brain: AgentBrainClient) {
    interface Listener {
        fun onEvent(text: String)
        fun onFinished(success: Boolean)
    }

    private val main = Handler(Looper.getMainLooper())
    private var running = false
    private var task = ""
    private var step = 0
    private var listener: Listener? = null
    private val history = JSONArray()

    fun start(taskText: String, listener: Listener) {
        if (running) return
        val service = UcoaAccessibilityService.instance
        if (service == null) { listener.onEvent("العقل: خدمة التحكم غير متاحة"); listener.onFinished(false); return }
        running = true; task = taskText; step = 0; history.clear(); this.listener = listener
        listener.onEvent("العقل العالمي: بدأ حلقة الفهم ← الملاحظة ← التنفيذ ← التحقق.")
        next()
    }

    fun stop() { running = false; listener?.onEvent("العقل العالمي: تم إيقاف المهمة.") }

    private fun next() {
        if (!running) return
        if (step >= 60) { finish(false, "وصلت المهمة إلى الحد الآمن لخطوات التنفيذ."); return }
        val service = UcoaAccessibilityService.instance
        if (service == null) { finish(false, "فقدت خدمة التحكم أثناء التنفيذ."); return }

        service.captureScreenshotBase64 { screenshot ->
            if (!running) return@captureScreenshotBase64
            val ui = service.observeUi(220)
            listener?.onEvent("العقل: يقرأ حالة التطبيق الحالية (الخطوة ${step + 1}).")
            brain.step(task, step, history, ui, screenshot) { response ->
                main.post {
                    if (!running) return@post
                    if (!response.ok || response.body == null) {
                        finish(false, "تعذر الوصول إلى عقل AI: ${response.error ?: "استجابة غير صالحة"}")
                        return@post
                    }
                    val decision = response.body
                    val message = decision.optString("message").trim()
                    if (message.isNotBlank()) listener?.onEvent("العقل: $message")
                    val done = decision.optBoolean("done", false)
                    if (done || decision.optString("action").equals("done", true)) {
                        finish(true, decision.optString("message", "اكتملت المهمة.")); return@post
                    }
                    val action = decision.optString("action").trim()
                    val params = decision.optJSONObject("params") ?: decision
                    if (action.isBlank()) { finish(false, "العقل أعاد قرارًا بلا فعل قابل للتنفيذ."); return@post }
                    execute(action, params) { ok, detail ->
                        main.post {
                            history.put(JSONObject().apply {
                                put("step", step)
                                put("action", action)
                                put("ok", ok)
                                put("detail", detail.take(500))
                            })
                            listener?.onEvent("التنفيذ: $action — ${if (ok) "نجح" else "فشل"}${if (detail.isNotBlank()) " — $detail" else ""}")
                            step++
                            main.postDelayed({ next() }, params.optLong("wait_after_ms", 700L).coerceIn(150L, 5000L))
                        }
                    }
                }
            }
        }
    }

    private fun execute(action: String, p: JSONObject, cb: (Boolean, String) -> Unit) {
        val s = UcoaAccessibilityService.instance ?: run { cb(false, "service_offline"); return }
        when (action.lowercase()) {
            "open_url" -> cb(s.openUrl(p.optString("url")), "")
            "open_app_by_name" -> cb(s.openAppByName(p.optString("app_name")), p.optString("app_name"))
            "click_any_text" -> cb(s.clickAnyText(array(p, "texts")), "")
            "type_into_any" -> cb(s.typeIntoAny(array(p, "hints"), p.optString("text")), "")
            "tap" -> cb(s.tap(p.optDouble("x").toFloat(), p.optDouble("y").toFloat()), "")
            "long_press" -> cb(s.longPress(p.optDouble("x").toFloat(), p.optDouble("y").toFloat(), p.optLong("duration_ms", 700L)), "")
            "swipe" -> cb(s.swipe(p.optDouble("x1").toFloat(), p.optDouble("y1").toFloat(), p.optDouble("x2").toFloat(), p.optDouble("y2").toFloat(), p.optLong("duration_ms", 500L)), "")
            "back" -> cb(s.back(), "")
            "home" -> cb(s.home(), "")
            "wait" -> { main.postDelayed({ cb(true, "waited") }, p.optLong("ms", 1000L).coerceIn(100L, 10000L)) }
            "observe" -> cb(true, s.observeUi(220))
            else -> cb(false, "unsupported_action=$action")
        }
    }

    private fun array(obj: JSONObject, key: String): List<String> = buildList {
        obj.optJSONArray(key)?.let { a -> for (i in 0 until a.length()) add(a.optString(i)) }
    }

    private fun finish(success: Boolean, message: String) {
        running = false
        if (message.isNotBlank()) listener?.onEvent(message)
        listener?.onFinished(success)
    }
}
