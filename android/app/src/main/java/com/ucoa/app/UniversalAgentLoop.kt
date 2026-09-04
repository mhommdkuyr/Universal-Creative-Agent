package com.ucoa.app

import android.os.Handler
import android.os.Looper
import org.json.JSONArray
import org.json.JSONObject

/** Observe -> visual/semantic reasoning -> safety verification -> act -> verify loop. */
class UniversalAgentLoop(private val brain: AgentBrainClient) {
    interface Listener {
        fun onEvent(text: String)
        fun onFinished(success: Boolean)
        fun onConfirmationRequired(reasons: String) { onEvent("تأكيد مطلوب قبل التنفيذ: $reasons") }
    }
    private val main = Handler(Looper.getMainLooper())
    private var running = false
    private var task = ""
    private var step = 0
    private var listener: Listener? = null
    private var history = JSONArray()
    private var attachments: List<String> = emptyList()

    fun start(taskText: String, listener: Listener, selectedAttachments: List<String> = emptyList()) {
        if (running) return
        if (UcoaAccessibilityService.instance == null) {
            listener.onEvent("العقل: خدمة التحكم غير متاحة")
            listener.onFinished(false)
            return
        }
        running = true
        task = taskText
        step = 0
        history = JSONArray()
        this.listener = listener
        attachments = selectedAttachments
        listener.onEvent("العقل العالمي: بدأ الإدراك البصري ← التفكير ← التحقق ← التنفيذ.")
        next()
    }

    fun stop() {
        running = false
        listener?.onEvent("العقل العالمي: تم إيقاف المهمة.")
    }

    private fun next() {
        if (!running) return
        if (step >= 60) {
            finish(false, "وصلت المهمة إلى الحد الآمن لخطوات التنفيذ.")
            return
        }
        val service = UcoaAccessibilityService.instance ?: run {
            finish(false, "فقدت خدمة التحكم.")
            return
        }
        service.captureScreenshotBase64 { screenshot ->
            if (!running) return@captureScreenshotBase64
            val ui = service.observeUi(260)
            brain.step(task, step, history, ui, screenshot, service.installedAppLabels(), attachments, false) { response ->
                main.post {
                    if (!running) return@post
                    if (!response.ok || response.body == null) {
                        finish(false, "تعذر الوصول إلى عقل AI: ${response.error ?: "استجابة غير صالحة"}")
                        return@post
                    }
                    val decision = response.body
                    decision.optString("visual_observation").trim().takeIf { it.isNotBlank() }?.let {
                        listener?.onEvent("الرؤية: $it")
                    }
                    decision.optString("message").trim().takeIf { it.isNotBlank() }?.let {
                        listener?.onEvent("العقل: $it")
                    }
                    val verification = decision.optJSONObject("verification")
                    if (verification?.optBoolean("requires_confirmation", false) == true) {
                        val reasons = verification.optJSONArray("reasons")?.let { a -> (0 until a.length()).joinToString(", ") { a.optString(it) } } ?: "policy"
                        listener?.onConfirmationRequired(reasons)
                        finish(false, "تم إيقاف التنفيذ الآلي حفاظًا على الأمان.")
                        return@post
                    }
                    val action = decision.optString("action").trim()
                    val params = decision.optJSONObject("params") ?: decision
                    if (decision.optBoolean("done", false) || action.equals("done", true)) {
                        finish(true, decision.optString("message", "اكتملت المهمة."))
                        return@post
                    }
                    if (action.isBlank()) {
                        finish(false, "العقل أعاد قرارًا بلا فعل.")
                        return@post
                    }
                    execute(action, params) { ok, detail ->
                        history.put(JSONObject().apply {
                            put("step", step)
                            put("action", action)
                            put("ok", ok)
                            put("detail", detail.take(700))
                        })
                        listener?.onEvent("التنفيذ: $action — ${if (ok) "نجح" else "فشل"}")
                        step++
                        main.postDelayed({ next() }, params.optLong("wait_after_ms", 700L).coerceIn(150L, 5000L))
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
            "share_attachment" -> {
                val index = p.optInt("index", 0)
                val target = attachments.getOrNull(index)
                if (target == null) cb(false, "attachment_index_missing=$index") else cb(s.shareAttachment(target, p.optString("target_package").takeIf { it.isNotBlank() }), "attachment_$index")
            }
            "tap" -> cb(s.tap(p.optDouble("x").toFloat(), p.optDouble("y").toFloat()), "")
            "long_press" -> cb(s.longPress(p.optDouble("x").toFloat(), p.optDouble("y").toFloat(), p.optLong("duration_ms", 700L)), "")
            "swipe" -> cb(s.swipe(p.optDouble("x1").toFloat(), p.optDouble("y1").toFloat(), p.optDouble("x2").toFloat(), p.optDouble("y2").toFloat(), p.optLong("duration_ms", 500L)), "")
            "back" -> cb(s.back(), "")
            "home" -> cb(s.home(), "")
            "wait" -> main.postDelayed({ cb(true, "waited") }, p.optLong("ms", 1000L).coerceIn(100L, 10000L))
            "observe" -> cb(true, s.observeUi(260))
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
