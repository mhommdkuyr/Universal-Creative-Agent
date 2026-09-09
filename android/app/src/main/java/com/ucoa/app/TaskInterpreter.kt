package com.ucoa.app

class TaskInterpreter {
    data class PlanResult(val summary: String, val steps: List<String>, val taskType: String)

    fun analyze(text: String, attachments: List<String>): PlanResult {
        val lower = text.lowercase()
        val type = when {
            attachments.any { it.endsWith(".mp4", true) || it.endsWith(".mov", true) } ||
                lower.contains("فيديو") || lower.contains("مونتاج") || lower.contains("capcut") ||
                lower.contains("ai creative studio") -> "creative_video"
            attachments.any { it.endsWith(".png", true) || it.endsWith(".jpg", true) || it.endsWith(".jpeg", true) } ||
                lower.contains("صورة") || lower.contains("تصميم") -> "creative_design"
            lower.contains("برمج") || lower.contains("كود") || lower.contains("github") -> "software"
            lower.contains("متصفح") || lower.contains("موقع") || lower.contains("افتح") -> "browser"
            else -> "general"
        }
        val base = when (type) {
            "creative_video" -> listOf(
                "تحليل الملف/المرجع بصريًا وزمنيًا وصوتيًا",
                "استخراج أسلوب المونتاج والنصوص والانتقالات والإيقاع",
                "تحديد مهارة التطبيق أو محرر الويب المناسب وفتح الهدف",
                "تنفيذ عناصر المهمة مع مراقبة واجهة المستخدم بعد كل مرحلة",
                "التحقق من النتيجة ثم إعادة المحاولة أو الإصلاح عند الحاجة"
            )
            "creative_design" -> listOf(
                "تحليل المرجع والهدف والأبعاد والعناصر المطلوبة",
                "اختيار محرر مناسب وفتح الهدف",
                "إنشاء التصميم الأولي ومراقبة واجهة التحرير",
                "مقارنة النتيجة بالمطلوب وإصلاح الاختلافات",
                "تصدير النتيجة بالجودة المناسبة"
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
