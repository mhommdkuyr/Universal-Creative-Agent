package com.ucoa.app

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.speech.RecognizerIntent
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.work.Data
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import org.json.JSONArray

class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var chat: LinearLayout
    private lateinit var input: EditText
    private lateinit var connectButton: Button
    private val selectedMedia = mutableListOf<String>()
    private val planner = AgentActionPlanner()
    private var latestPlan: TaskInterpreter.PlanResult? = null
    private var latestActions = JSONArray()
    private var latestTaskText: String = ""
    private val pickMedia = 401
    private val speech = 402

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildUi())
        refreshConnectionState()
    }

    override fun onResume() {
        super.onResume()
        if (::status.isInitialized) refreshConnectionState()
    }

    private fun buildUi(): View {
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(Color.WHITE) }
        val top = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(28, 30, 28, 12) }
        val title = TextView(this).apply { text = "Universal Creative Agent"; textSize = 21f; setTextColor(Color.BLACK); gravity = Gravity.CENTER_HORIZONTAL }
        status = TextView(this).apply { textSize = 13f; gravity = Gravity.CENTER_HORIZONTAL; setPadding(0, 8, 0, 10) }
        connectButton = Button(this).apply { text = "ربط الهاتف بنقرة واحدة"; setOnClickListener { connectPhone() } }
        top.addView(title); top.addView(status); top.addView(connectButton); root.addView(top)

        val scroll = ScrollView(this).apply { setFillViewport(true); layoutParams = LinearLayout.LayoutParams(-1, 0, 1f) }
        chat = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(24, 18, 24, 24) }
        addAssistantBubble("أنا جاهز. اكتب أي شيء تريد تنفيذه، وارفع فيديو أو صورة أو ملف عند الحاجة. سأحلل المطلوب وأعرض خطة قابلة للتنفيذ قبل التشغيل.")
        scroll.addView(chat); root.addView(scroll)

        val composer = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(14, 8, 14, 14) }
        val attach = ImageButton(this).apply { setImageResource(android.R.drawable.ic_menu_add); contentDescription = "رفع الوسائط"; setBackgroundColor(Color.TRANSPARENT); setOnClickListener { chooseMedia() } }
        val mic = ImageButton(this).apply { setImageResource(android.R.drawable.ic_btn_speak_now); contentDescription = "الصوت"; setBackgroundColor(Color.TRANSPARENT); setOnClickListener { startSpeech() } }
        input = EditText(this).apply { hint = "اكتب ما تريد تنفيذه…"; minLines = 1; maxLines = 5; setPadding(16, 12, 16, 12); layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f) }
        val send = ImageButton(this).apply { setImageResource(android.R.drawable.ic_menu_send); contentDescription = "إرسال"; setBackgroundColor(Color.TRANSPARENT); setOnClickListener { analyzeTask() } }
        composer.addView(attach, LinearLayout.LayoutParams(48, 56)); composer.addView(mic, LinearLayout.LayoutParams(48, 56)); composer.addView(input); composer.addView(send, LinearLayout.LayoutParams(56, 56)); root.addView(composer)
        return root
    }

    private fun refreshConnectionState() {
        val enabled = PermissionCoordinator.isAccessibilityEnabled(this)
        val live = PermissionCoordinator.isServiceLive()
        status.text = when {
            live -> "● متصل ويستطيع التفاعل مع الهاتف"
            enabled -> "● الصلاحية مفعلة — جارٍ انتظار الخدمة"
            else -> "○ غير متصل — فعّل الوصول مرة واحدة"
        }
        connectButton.text = when { live -> "الهاتف متصل"; enabled -> "فتح إعدادات الوصول"; else -> "ربط الهاتف بنقرة واحدة" }
        connectButton.isEnabled = !live
        if (enabled && !live) window.decorView.postDelayed({ if (!PermissionCoordinator.isServiceLive()) refreshConnectionState() }, 700)
    }

    private fun connectPhone() {
        PermissionCoordinator.openAccessibilitySettings(this)
        Toast.makeText(this, "فعّل Universal Creative Agent ثم ارجع. بعد ذلك سيبدأ التحكم من داخل التطبيق.", Toast.LENGTH_LONG).show()
    }

    private fun chooseMedia() {
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            type = "*/*"; putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true); addCategory(Intent.CATEGORY_OPENABLE)
        }, pickMedia)
    }

    private fun startSpeech() {
        try {
            startActivityForResult(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ar-SA")
                putExtra(RecognizerIntent.EXTRA_PROMPT, "تحدث بطلبك")
            }, speech)
        } catch (_: Exception) { Toast.makeText(this, "التعرف الصوتي غير متاح على هذا الجهاز.", Toast.LENGTH_SHORT).show() }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != RESULT_OK || data == null) return
        if (requestCode == pickMedia) {
            data.clipData?.let { clip -> for (i in 0 until clip.itemCount) selectedMedia.add(clip.getItemAt(i).uri.toString()) }
                ?: data.data?.let { selectedMedia.add(it.toString()) }
            input.hint = "أضفت ${selectedMedia.size} ملف — اكتب المطلوب"
        } else if (requestCode == speech) {
            data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()?.let { input.setText(it) }
        }
    }

    private fun analyzeTask() {
        latestTaskText = input.text.toString().trim(); if (latestTaskText.isEmpty()) return
        addUserBubble(latestTaskText + if (selectedMedia.isNotEmpty()) "\n📎 ${selectedMedia.size} ملف" else "")
        val result = planner.plan(latestTaskText, selectedMedia)
        latestPlan = result.plan
        latestActions = result.actions
        if (selectedMedia.isNotEmpty()) queueBackgroundPreparation(latestTaskText)
        addPlanCard(result.plan, result.target?.id)
        input.setText("")
    }

    private fun queueBackgroundPreparation(task: String) {
        val builder = Data.Builder().putString("task", task).putInt("media_count", selectedMedia.size)
        builder.putStringArray("media_uris", selectedMedia.toTypedArray())
        WorkManager.getInstance(this).enqueue(OneTimeWorkRequestBuilder<MediaBackgroundWorker>().setInputData(builder.build()).build())
        addAssistantBubble("الوسائط أُضيفت لمعالجة الخلفية المحلية.")
    }

    private fun addAssistantBubble(text: String) = addBubble(text, false)
    private fun addUserBubble(text: String) = addBubble(text, true)
    private fun addBubble(text: String, user: Boolean) {
        val tv = TextView(this).apply {
            this.text = text; textSize = 16f; setTextColor(if (user) Color.WHITE else Color.DKGRAY)
            setPadding(18, 18, 18, 18); setBackgroundColor(if (user) 0xFF222222.toInt() else 0xFFF2F2F2.toInt())
        }
        chat.addView(tv, LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT).apply { setMargins(0, 0, 0, 18) })
    }

    private fun addPlanCard(plan: TaskInterpreter.PlanResult, skillId: String?) {
        val card = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(22, 20, 22, 20); setBackgroundColor(0xFFF7F7F7.toInt()) }
        val heading = TextView(this).apply { text = if (skillId != null) "خطة التنفيذ — مهارة $skillId" else "خطة التنفيذ"; textSize = 18f; setTextColor(Color.BLACK) }
        val summary = TextView(this).apply { text = plan.summary; textSize = 14f; setPadding(0, 10, 0, 8) }
        val steps = TextView(this).apply { text = plan.steps.mapIndexed { i, s -> "${i + 1}. $s" }.joinToString("\n"); textSize = 15f; setPadding(0, 8, 0, 18) }
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val review = Button(this).apply { text = "مراجعة وتعديل"; setOnClickListener { showReview(plan) } }
        val execute = Button(this).apply { text = "تنفيذ الآن"; setOnClickListener { executePlan(card) } }
        row.addView(execute, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)); row.addView(review, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        card.addView(heading); card.addView(summary); card.addView(steps); card.addView(row)
        chat.addView(card, LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT).apply { setMargins(0, 0, 0, 18) })
    }

    private fun showReview(plan: TaskInterpreter.PlanResult) {
        val editor = EditText(this).apply { setText(plan.steps.mapIndexed { i, s -> "${i + 1}. $s" }.joinToString("\n")); minLines = 8 }
        AlertDialog.Builder(this).setTitle("تعديل خطة التنفيذ").setView(editor).setNegativeButton("إلغاء", null).setPositiveButton("حفظ الخطة") { _, _ ->
            val newSteps = editor.text.toString().lines().map { it.trim() }.filter { it.isNotEmpty() }.map { it.replaceFirst(Regex("^\\d+\\.\\s*"), "") }
            latestPlan = plan.copy(steps = newSteps)
            addAssistantBubble("تم حفظ الخطة المعدلة. سيُستخدم محتواها في المتابعة.")
        }.show()
    }

    private fun executePlan(card: View) {
        if (!PermissionCoordinator.isServiceLive()) {
            Toast.makeText(this, "فعّل ربط الهاتف أولًا.", Toast.LENGTH_LONG).show(); connectPhone(); return
        }
        card.isEnabled = false
        addAssistantBubble("بدأ وكيل التنفيذ: فتح الهدف، مراقبة الواجهة، تنفيذ عناصر المهارة، ثم تسجيل النتيجة.")
        SmartActionRunner().run(latestActions,
            onEvent = { event -> runOnUiThread {
                status.text = event.take(240)
                if (event.startsWith("UI:")) addAssistantBubble(event.take(1200))
            } },
            onFinished = { runOnUiThread { addAssistantBubble("انتهت دورة التنفيذ الحالية. راجع سجل المراقبة لمعرفة الأفعال التي نجحت أو تم تجاوزها."); card.isEnabled = true } }
        )
    }
}
