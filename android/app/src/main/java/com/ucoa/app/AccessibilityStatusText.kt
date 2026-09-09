package com.ucoa.app

object AccessibilityStatusText {
    fun text(status: ConnectionStatus): String = when (status) {
        ConnectionStatus.CONNECTED -> "● متصل ويستطيع التفاعل مع الهاتف"
        ConnectionStatus.ENABLED_WAITING -> "● الصلاحية مفعلة — جارٍ تهيئة الخدمة"
        ConnectionStatus.DISCONNECTED -> "○ غير متصل — فعّل الوصول مرة واحدة"
    }
}
