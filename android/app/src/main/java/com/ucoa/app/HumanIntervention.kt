package com.ucoa.app

import org.json.JSONObject

/** Detects only blockers that genuinely require a human; ordinary failures stay inside recovery. */
object HumanIntervention {
    data class Request(val kind:String,val title:String,val message:String,val actionLabel:String)

    fun detect(decision: JSONObject, visualSummary: String): Request? {
        if (!decision.optBoolean("requires_human", false) && decision.optString("human_action").isBlank()) {
            val text=(visualSummary+" "+decision.optString("message")).lowercase()
            return when {
                listOf("sign up","create account","إنشاء حساب","سجل حساب","التسجيل مطلوب").any{text.contains(it)} -> Request("signup","التسجيل مطلوب","أنشئ الحساب ثم عد إلى التطبيق لمتابعة المهمة.","تم التسجيل — متابعة")
                listOf("verification code","رمز التحقق","تحقق من البريد","verify your email").any{text.contains(it)} -> Request("verification","رمز التحقق مطلوب","أدخل رمز التحقق في الخدمة ثم عد للمتابعة.","تم التحقق — متابعة")
                listOf("insufficient credits","not enough credits","no credits","نفاد الرصيد","لا يوجد رصيد","رصيد غير كاف").any{text.contains(it)} -> Request("credits","الخدمة تحتاج رصيدًا","لم يبق حل آلي متاح. يمكنك الاشتراك ثم استئناف المهمة من نفس الخطوة.","متابعة الاشتراك")
                listOf("subscription required","subscribe to continue","الاشتراك مطلوب").any{text.contains(it)} -> Request("subscription","الاشتراك مطلوب","أكمل الاشتراك في الخدمة ثم عد لمتابعة المهمة من نقطة التوقف.","متابعة الاشتراك")
                else -> null
            }
        }
        val kind=decision.optString("human_action").ifBlank { decision.optString("human_kind","user_input") }
        return when(kind.lowercase()) {
            "signup","sign_up" -> Request("signup","التسجيل مطلوب","أنشئ الحساب ثم عد إلى التطبيق لمتابعة المهمة.","تم التسجيل — متابعة")
            "verification","verification_code","otp" -> Request("verification","رمز التحقق مطلوب","أدخل رمز التحقق ثم عد إلى التطبيق لمتابعة المهمة.","تم التحقق — متابعة")
            "subscription" -> Request("subscription","الاشتراك مطلوب","أكمل الاشتراك ثم عد إلى التطبيق لمتابعة المهمة.","متابعة الاشتراك")
            "credits" -> Request("credits","الخدمة تحتاج رصيدًا","يمكنك الاشتراك ثم استئناف المهمة من نقطة التوقف.","متابعة الاشتراك")
            else -> Request("user_input","تدخل المستخدم مطلوب",decision.optString("human_message","نفذ الإجراء الظاهر أمامك ثم عد لمتابعة المهمة."),decision.optString("human_button","تم — متابعة"))
        }
    }
}
