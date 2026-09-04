package com.ucoa.app

class TaskInterpreter {
    data class PlanResult(val summary: String, val steps: List<String>, val taskType: String)

    fun analyze(text: String, attachments: List<String>): PlanResult {
        val lower = text.lowercase()
        val type = when {
            attachments.any { it.endsWith(".mp4", true) || it.endsWith(".mov", true) } || lower.contains("فيديو") || lower.contains("capcut") -> "creative_video"
            attachments.any { it.endsWith(".png", true) || it.endsWith(".jpg", true) || it.endsWith(".jpeg", true) } || lower.contains("صورة") || lower.contains("تصميم") -> "creative_design"
            lower.contains("برمج") || lower.contains("كود") || lower.contains("github") -> "software"
            lower.contains("متصفح") || lower.contains("موقع") || lower.contains("افتح") -> "browser"
            else -> "general"
        }
        val base = when (type) {
            "creative_video" -> listOf(
                "تحليل الملف/الرابط والمرجع بصريًا وزمنيًا وصوتيًا",
                "استخراج أسلوب المونتاج والنصوص والانتقالات والإيقاع",
                "اختيار التطبيق/المحرر المناسب وتنفيذ الخطة",
                "إخراج نسخة تجريبية ثم فحصها بصريًا وزمنيًا وصوتيًا",
                "إصلاح الاختلافات ثم إخراج النتيجة النهائية"
            )
            "creative_design" -> listOf(
                "تحليل المرجع والهدف والأبعاد والعناصر المطلوبة",
                "إنشاء تصميم أولي داخل محرر مناسب",
                "مقارنة التصميم مع المطلوب وإصلاح الاختلافات",
                "تصدير النتيجة بجودة مناسبة"
            )
            "software" -> listOf(
                "فحص المشروع والملفات المرتبطة بالمهمة",
                "صياغة خطة التعديل والاختبارات المطلوبة",
                "تنفيذ التغييرات وتشغيل الاختبارات",
                "إصلاح أي فشل ثم تسليم النتيجة"
            )
            "browser" -> listOf(
                "فتح الصفحة المناسبة ومراقبة عناصرها",
                "تنفيذ الأفعال المطلوبة بالتسلسل",
                "التحقق من النتيجة قبل الإنهاء"
            )
            else -> listOf(
                "فهم المطلوب وتحديد أفضل طريقة للتنفيذ",
                "تنفيذ الخطوات مع مراقبة النتيجة",
                "التحقق من النتيجة وإصلاح ما يلزم"
            )
        }
        return PlanResult("سأنفذ المهمة بعد مراجعة الخطة أدناه.", base, type)
    }
}
