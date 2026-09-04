package com.ucoa.app

import org.json.JSONArray
import org.json.JSONObject

/** Converts a natural-language task into executable, observable UI actions. */
class AgentActionPlanner {
    data class Result(
        val plan: TaskInterpreter.PlanResult,
        val actions: JSONArray,
        val target: AppSkillRegistry.Skill?
    )

    fun plan(text: String, attachments: List<String>): Result {
        val base = TaskInterpreter().analyze(text, attachments)
        val target = AppSkillRegistry.resolve(text)
        val actions = JSONArray()
        val lower = text.lowercase()

        if (target?.id == "ai_creative_studio") {
            val prompt = buildCreativePrompt(text, attachments)
            actions.put(JSONObject().apply { put("action", "open_url"); put("url", target.webUrl); put("delay_ms", 900) })
            actions.put(JSONObject().apply {
                put("action", "click_any_text")
                put("texts", JSONArray(listOf("Create Video", "Generate Video", "Video", "VIDÉO", "فيديو", "إنشاء فيديو", "توليد فيديو")))
                put("delay_ms", 900)
                put("optional", true)
            })
            actions.put(JSONObject().apply {
                put("action", "click_any_text")
                put("texts", JSONArray(listOf("Create", "New", "إنشاء", "جديد", "Studio")))
                put("delay_ms", 700)
                put("optional", true)
            })
            actions.put(JSONObject().apply {
                put("action", "type_into_any")
                put("hints", JSONArray(listOf("Prompt", "Describe", "prompt", "وصف", "اكتب")))
                put("text", prompt)
                put("delay_ms", 700)
                put("optional", true)
            })
            actions.put(JSONObject().apply {
                put("action", "observe")
                put("delay_ms", 700)
            })
            actions.put(JSONObject().apply {
                put("action", "click_any_text")
                put("texts", JSONArray(listOf("Generate", "Create", "Start", "توليد", "إنشاء", "ابدأ")))
                put("delay_ms", 1000)
                put("optional", true)
            })
            actions.put(JSONObject().apply { put("action", "observe"); put("delay_ms", 1800) })
        } else {
            target?.packageAliases?.firstOrNull()?.let { alias ->
                actions.put(JSONObject().apply {
                    put("action", "open_app_by_name")
                    put("app_name", alias)
                    put("delay_ms", 800)
                })
            }
            actions.put(JSONObject().apply { put("action", "observe"); put("delay_ms", 800) })
        }

        val summary = if (target != null) {
            "وجدت مهارة الهدف «${target.id}». سأفتح الهدف، أراقب واجهته، وأنفذ الأفعال المناسبة خطوةً بخطوة مع التحقق من الواجهة."
        } else {
            base.summary
        }
        return Result(base.copy(summary = summary), actions, target)
    }

    private fun buildCreativePrompt(text: String, attachments: List<String>): String {
        val hasVideo = attachments.any { it.contains("video", true) || it.endsWith(".mp4", true) || it.endsWith(".mov", true) }
        val media = if (hasVideo) "استخدم الوسائط المرفوعة كأساس للمونتاج. " else "أنشئ مونتاجًا من العناصر المتاحة في المشروع. "
        return media + "أنشئ مونتاجًا احترافيًا ديناميكيًا مناسبًا للسوشيال ميديا، بإيقاع واضح وانتقالات سلسة ونصوص مقروءة وتوازن صوتي جيد. الطلب الأصلي: $text"
    }
}
