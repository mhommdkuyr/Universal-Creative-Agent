package com.ucoa.app

import android.app.Activity
import android.os.Bundle
import android.provider.Settings
import android.content.Intent
import android.graphics.Color
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject

class MainActivity : Activity() {
    private lateinit var status: TextView
    private val runner = ActionPlanRunner()

    private val appPackages = mapOf(
        "capcut" to "com.lemon.lvoverseas",
        "canva" to "com.canva.editor",
        "chrome" to "com.android.chrome",
        "youtube" to "com.google.android.youtube"
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val input = EditText(this).apply {
            hint = "مثال: افتح CapCut / اضغط Export / اكتب النص / رجوع"
            minLines = 4
            setTextColor(Color.BLACK)
        }
        val target = EditText(this).apply {
            hint = "الهدف (CapCut / Canva / Chrome)"
            setTextColor(Color.BLACK)
        }
        val enable = Button(this).apply { text = "تفعيل الوصول للنظام" }
        val run = Button(this).apply { text = "تنفيذ المهمة الآن" }
        val demo = Button(this).apply { text = "اختبار حقيقي: تشغيل CapCut" }
        status = TextView(this).apply {
            text = "Universal Creative Agent v0.4\nجاهز — يجب تفعيل Accessibility قبل التنفيذ"
            setPadding(0, 24, 0, 24)
        }

        enable.setOnClickListener { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
        demo.setOnClickListener {
            val pkg = appPackages["capcut"]
            if (pkg == null) return@setOnClickListener
            val plan = JSONArray().put(JSONObject().apply {
                put("action", "open_app")
                put("package", pkg)
                put("delay_ms", 250)
            }).toString()
            status.text = "بدء الاختبار الحقيقي…\nفتح CapCut"
            runner.run(plan) { event -> status.append("\n$event") }
        }
        run.setOnClickListener {
            val plan = parseSimpleArabicCommand(input.text.toString(), target.text.toString())
            if (plan.length() == 0) {
                status.text = "لم أتعرف على أمر تنفيذي. استخدم: افتح / اضغط / اكتب / رجوع / الرئيسية."
                return@setOnClickListener
            }
            status.text = "تنفيذ المهمة…"
            runner.run(plan.toString()) { event -> status.append("\n$event") }
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 48, 32, 32)
        }
        listOf(input, target, enable, demo, run, status).forEach {
            root.addView(it, ViewGroup.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT))
        }
        setContentView(root)
    }

    private fun parseSimpleArabicCommand(command: String, target: String): JSONArray {
        val result = JSONArray()
        val parts = command.split(Regex("\\s*[؛;\\n]+\\s*|\\s+(?=ثم\\s)"))
        for (raw in parts) {
            val s = raw.trim()
            when {
                s.startsWith("افتح ") || s.startsWith("شغل ") || s.startsWith("شغّل ") -> {
                    val name = s.substringAfter(' ').trim().lowercase()
                    val pkg = appPackages[name] ?: appPackages[target.trim().lowercase()]
                    if (pkg != null) result.put(JSONObject().apply { put("action", "open_app"); put("package", pkg) })
                }
                s.startsWith("اضغط ") -> result.put(JSONObject().apply { put("action", "click_text"); put("text", s.removePrefix("اضغط ").trim()) })
                s.startsWith("اكتب ") -> result.put(JSONObject().apply { put("action", "type_text"); put("text", s.removePrefix("اكتب ") ) })
                s == "رجوع" || s == "عودة" -> result.put(JSONObject().apply { put("action", "back") })
                s == "الرئيسية" || s == "الصفحة الرئيسية" -> result.put(JSONObject().apply { put("action", "home") })
            }
        }
        return result
    }
}
