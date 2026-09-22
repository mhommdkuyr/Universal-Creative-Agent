package com.ucoa.app

import org.json.JSONObject

/** Compatibility facade kept for older callers. Execution is now queued through the single cloud device bridge. */
class UniversalAgentLoop(private val brain: AgentBrainClient) {
    interface Listener { fun onEvent(text: String); fun onFinished(success: Boolean); fun onConfirmationRequired(reasons: String) { onEvent("تأكيد مطلوب: $reasons") }; fun onHumanIntervention(request: HumanIntervention.Request) { onEvent("تدخل المستخدم مطلوب: ${request.title}") } }
    @Volatile private var running = false
    fun start(taskText: String, listener: Listener, selectedAttachments: List<String> = emptyList()) {
        if (running) return
        if (UcoaAccessibilityService.instance == null) { listener.onEvent("خدمة التحكم غير متاحة"); listener.onFinished(false); return }
        running = true; listener.onEvent("تم تسليم المهمة إلى جسر UCOA السحابي.")
        brain.queueTask(taskText, selectedAttachments, JSONObject().put("compatibility_facade", true).put("evidence_required", true)) { r ->
            running = false
            if (r.ok) listener.onEvent("الجسر استلم المهمة؛ التنفيذ سيظهر داخل المحادثة.") else listener.onEvent("فشل تسليم المهمة: ${r.error ?: "خطأ غير معروف"}")
            listener.onFinished(r.ok)
        }
    }
    fun resume() { UcoaDiagnostics.log("AGENT", "resume ignored: cloud bridge owns execution") }
    fun stop() { running = false; UcoaDiagnostics.log("AGENT", "stop requested; cloud bridge owns execution") }
    fun isWaitingForHuman() = false
}
