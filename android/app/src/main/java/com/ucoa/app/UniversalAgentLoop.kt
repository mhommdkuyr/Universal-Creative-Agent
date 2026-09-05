package com.ucoa.app

import android.os.Handler
import android.os.Looper
import org.json.JSONArray
import org.json.JSONObject

/** Real observe -> multimodal controller -> safety -> action -> post-action verification loop. */
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
        if (UcoaAccessibilityService.instance == null) { listener.onEvent("العقل: خدمة التحكم غير متاحة"); listener.onFinished(false); return }
        running = true; task = taskText; step = 0; history = JSONArray(); this.listener = listener; attachments = selectedAttachments
        listener.onEvent("العقل العالمي: الإدراك البصري ← التفكير ← الأمان ← التنفيذ ← التحقق.")
        persist("running"); next()
    }

    fun stop() { running = false; persist("stopped"); listener?.onEvent("العقل العالمي: تم إيقاف المهمة.") }

    private fun next() {
        if (!running) return
        if (step >= 60) { finish(false, "وصلت المهمة إلى الحد الآمن لخطوات التنفيذ."); return }
        val service = UcoaAccessibilityService.instance ?: run { finish(false, "فقدت خدمة التحكم."); return }

        // Explicit app bootstrap is a local deterministic operation. We do it before
        // asking the cloud model so a slow/unavailable planner cannot prevent the
        // agent from ever reaching the requested application.
        if (step == 0) {
            val requestedApp = requestedAppName(task)
            if (requestedApp != null && service.openAppByName(requestedApp)) {
                listener?.onEvent("التنفيذ المحلي: فتح $requestedApp")
                history.put(JSONObject().apply { put("step", 0); put("action", "open_app_by_name"); put("ok", true); put("detail", requestedApp) })
                persist("opened_$requestedApp")
                step = 1
                main.postDelayed({ next() }, 1200L)
                return
            }
        }

        service.captureScreenshotBase64 { beforeScreenshot ->
            if (!running) return@captureScreenshotBase64
            val beforeUi = service.observeUi(320)
            brain.step(task, step, history, beforeUi, beforeScreenshot, service.installedAppLabels(), attachments, false) { response ->
                main.post {
                    if (!running) return@post
                    if (!response.ok || response.body == null) { finish(false, "تعذر الوصول إلى عقل AI: ${response.error ?: "استجابة غير صالحة"}"); return@post }
                    val decision = response.body
                    val vp = decision.optString("vision_provider").trim()
                    val visualSummary = decision.optJSONObject("visual_observation")?.optString("screen_summary", "")?.trim().orEmpty()
                    if (visualSummary.isNotBlank()) listener?.onEvent("الرؤية[$vp]: $visualSummary")
                    decision.optString("message").trim().takeIf { it.isNotBlank() }?.let { listener?.onEvent("العقل: $it") }
                    val verification = decision.optJSONObject("verification")
                    if (verification?.optBoolean("requires_confirmation", false) == true) {
                        val reasons = verification.optJSONArray("reasons")?.let { a -> (0 until a.length()).joinToString(", ") { a.optString(it) } } ?: "policy"
                        listener?.onConfirmationRequired(reasons); finish(false, "تم إيقاف التنفيذ الآلي حفاظًا على الأمان."); return@post
                    }
                    val action = decision.optString("action").trim(); val params = decision.optJSONObject("params") ?: decision
                    if (decision.optBoolean("done", false) || action.equals("done", true)) { finish(true, decision.optString("message", "اكتملت المهمة.")); return@post }
                    if (action.isBlank()) { finish(false, "العقل أعاد قرارًا بلا فعل."); return@post }
                    execute(action, params) { ok, detail -> main.post { afterAction(beforeUi, beforeScreenshot, action, decision, ok, detail) } }
                }
            }
        }
    }

    private fun requestedAppName(text: String): String? {
        val t = text.lowercase()
        val aliases = listOf(
            "capcut" to "CapCut", "كاب كات" to "CapCut",
            "youtube" to "YouTube", "يوتيوب" to "YouTube",
            "canva" to "Canva", "كانفا" to "Canva",
            "chrome" to "Chrome", "كروم" to "Chrome",
            "instagram" to "Instagram", "انستجرام" to "Instagram",
            "whatsapp" to "WhatsApp", "واتساب" to "WhatsApp",
            "telegram" to "Telegram", "تليجرام" to "Telegram"
        )
        return aliases.firstOrNull { t.contains(it.first) }?.second
    }

    private fun afterAction(beforeUi: String, beforeScreenshot: String?, action: String, decision: JSONObject, ok: Boolean, detail: String) {
        val service = UcoaAccessibilityService.instance ?: run { finish(false, "فقدت خدمة التحكم أثناء التحقق."); return }
        history.put(JSONObject().apply { put("step", step); put("action", action); put("ok", ok); put("detail", detail.take(700)) })
        listener?.onEvent("التنفيذ: $action — ${if (ok) "أُرسل" else "فشل محليًا"}")
        persist("step_$step")
        if (!ok) { step++; main.postDelayed({ next() }, 400L); return }
        service.captureScreenshotBase64 { afterScreenshot ->
            val afterUi = service.observeUi(320)
            brain.verifyResult(task, decision, beforeUi, afterUi, beforeScreenshot, afterScreenshot) { result ->
                main.post {
                    if (!running) return@post
                    val verified = result.ok && (result.body?.optBoolean("verified", false) ?: false)
                    if (verified) {
                        listener?.onEvent("التحقق: نجح وتغيرت حالة الشاشة.")
                        step++; persist("verified_$step")
                        main.postDelayed({ next() }, decision.optLong("wait_after_ms", 700L).coerceIn(150L, 5000L))
                    } else {
                        listener?.onEvent("التحقق: لم يثبت نجاح الإجراء؛ سأعيد الملاحظة بدل إعلان الاكتمال.")
                        step++; persist("verification_failed_$step")
                        main.postDelayed({ next() }, 600L)
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
            "click_any_text" -> cb(s.clickAnyText(array(p, "texts", "text")), "")
            "type_into_any" -> cb(s.typeIntoAny(array(p, "hints"), p.optString("text")), "")
            "share_attachment" -> { val index = p.optInt("index", 0); val target = attachments.getOrNull(index); if (target == null) cb(false, "attachment_index_missing=$index") else cb(s.shareAttachment(target, p.optString("target_package").takeIf { it.isNotBlank() }), "attachment_$index") }
            "tap" -> cb(s.tap(p.optDouble("x").toFloat(), p.optDouble("y").toFloat()), "")
            "long_press" -> cb(s.longPress(p.optDouble("x").toFloat(), p.optDouble("y").toFloat(), p.optLong("duration_ms", 700L)), "")
            "swipe" -> cb(s.swipe(p.optDouble("x1").toFloat(), p.optDouble("y1").toFloat(), p.optDouble("x2").toFloat(), p.optDouble("y2").toFloat(), p.optLong("duration_ms", 500L)), "")
            "back" -> cb(s.back(), "")
            "home" -> cb(s.home(), "")
            "wait" -> main.postDelayed({ cb(true, "waited") }, p.optLong("ms", 1000L).coerceIn(100L, 10000L))
            "observe" -> cb(true, s.observeUi(320))
            else -> cb(false, "unsupported_action=$action")
        }
    }

    private fun array(obj: JSONObject, key: String, fallbackKey: String? = null): List<String> = buildList {
        obj.optJSONArray(key)?.let { a -> for (i in 0 until a.length()) add(a.optString(i)) }
        if (isEmpty() && fallbackKey != null) obj.optString(fallbackKey).takeIf { it.isNotBlank() }?.let { add(it) }
    }

    private fun persist(status: String) { brain.persistExecutionState(task, step, history, status) }
    private fun finish(success: Boolean, message: String) { running = false; persist(if (success) "completed" else "failed"); if (message.isNotBlank()) listener?.onEvent(message); listener?.onFinished(success) }
}
