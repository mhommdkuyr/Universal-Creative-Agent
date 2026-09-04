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

class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var chat: LinearLayout
    private lateinit var input: EditText
    private lateinit var connectButton: Button
    private val selectedMedia = mutableListOf<String>()
    private lateinit var brain: AgentBrainClient
    private var latestPlan: TaskInterpreter.PlanResult? = null
    private var latestTaskText = ""
    private var latestPlanCard: View? = null
    private val pickMedia = 401
    private val speech = 402

    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState); brain = AgentBrainClient(this); setContentView(buildUi()); refreshConnectionState() }
    override fun onResume() { super.onResume(); if (::status.isInitialized) refreshConnectionState() }

    private fun buildUi(): View {
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(Color.WHITE) }
        val top = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(22, 26, 22, 10) }
        val title = TextView(this).apply { text = "Universal Creative Agent"; textSize = 21f; setTextColor(Color.BLACK); gravity = Gravity.CENTER_HORIZONTAL }
        status = TextView(this).apply { textSize = 13f; gravity = Gravity.CENTER_HORIZONTAL; setPadding(0, 8, 0, 8) }
        val settings = Button(this).apply { text = "إعداد عقل AI"; setOnClickListener { showBrainSettings() } }
        connectButton = Button(this).apply { text = "ربط الهاتف بنقرة واحدة"; setOnClickListener { connectPhone() } }
        top.addView(title); top.addView(status); top.addView(settings); top.addView(connectButton); root.addView(top)
        val scroll = ScrollView(this).apply { setFillViewport(true); layoutParams = LinearLayout.LayoutParams(-1, 0, 1f) }
        chat = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(22, 12, 22, 22) }
        addAssistantBubble("أنا جاهز. اكتب أي مهمة تريد تنفيذها على الهاتف أو المتصفح أو أي تطبيق. سأفهم المطلوب، أبني خطة، ثم أراقب الشاشة وأتخذ الإجراءات خطوةً بخطوة.")
        scroll.addView(chat); root.addView(scroll)
        val composer = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(12, 8, 12, 14) }
        val attach = ImageButton(this).apply { setImageResource(android.R.drawable.ic_menu_add); contentDescription = "رفع الوسائط"; setBackgroundColor(Color.TRANSPARENT); setOnClickListener { chooseMedia() } }
        val mic = ImageButton(this).apply { setImageResource(android.R.drawable.ic_btn_speak_now); contentDescription = "الصوت"; setBackgroundColor(Color.TRANSPARENT); setOnClickListener { startSpeech() } }
        input = EditText(this).apply { hint = "اكتب ما تريد تنفيذه…"; minLines = 1; maxLines = 5; setPadding(16, 12, 16, 12); layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f) }
        val send = ImageButton(this).apply { setImageResource(android.R.drawable.ic_menu_send); contentDescription = "إرسال"; setBackgroundColor(Color.TRANSPARENT); setOnClickListener { analyzeTask() } }
        composer.addView(attach, LinearLayout.LayoutParams(46, 54)); composer.addView(mic, LinearLayout.LayoutParams(46, 54)); composer.addView(input); composer.addView(send, LinearLayout.LayoutParams(54, 54)); root.addView(composer)
        return root
    }

    private fun refreshConnectionState() {
        val enabled = PermissionCoordinator.isAccessibilityEnabled(this); val live = PermissionCoordinator.isServiceLive(); val brainText = if (brain.configured()) " • عقل AI: جاهز" else " • عقل AI: غير مُعد"
        status.text = when { live -> "● الهاتف متصل — التحكم والمراقبة متاحان$brainText"; enabled -> "● الصلاحية مفعلة — جارٍ انتظار الخدمة$brainText"; else -> "○ غير متصل — فعّل الوصول مرة واحدة$brainText" }
        connectButton.text = when { live -> "الهاتف متصل"; enabled -> "إعادة فتح إعدادات الوصول"; else -> "ربط الهاتف بنقرة واحدة" }; connectButton.isEnabled = !live || enabled
    }

    private fun showBrainSettings() {
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(18, 8, 18, 4) }
        val endpoint = EditText(this).apply { hint = "عنوان Brain API"; setSingleLine(); setText(brain.endpoint().ifBlank { "https://ucoa-agent-brain.onrender.com" }) }
        val token = EditText(this).apply { hint = "رمز الوصول للخادم (اختياري)"; setSingleLine(); setText(brain.token()); inputType = 0x81 }
        box.addView(endpoint); box.addView(token)
        val dialog = AlertDialog.Builder(this).setTitle("ربط عقل AI العالمي").setView(box).setNegativeButton("إلغاء", null).setPositiveButton("حفظ") { _, _ -> brain.saveConfig(endpoint.text.toString(), token.text.toString()); refreshConnectionState(); addAssistantBubble("تم حفظ اتصال عقل AI العالمي.") }.create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL)?.setOnClickListener { }
        }
        dialog.setButton(AlertDialog.BUTTON_NEUTRAL, "اختبار الاتصال") { _, _ -> }
        dialog.show()
        dialog.getButton(AlertDialog.BUTTON_NEUTRAL)?.setOnClickListener {
            brain.saveConfig(endpoint.text.toString(), token.text.toString()); status.text = "يجري اختبار اتصال عقل AI…"
            brain.plan("اختبار اتصال فقط. لا تنفذ أي إجراء على الهاتف.", emptyList()) { r -> runOnUiThread { status.text = if (r.ok) "● تم الاتصال بعقل AI" else "○ فشل الاتصال: ${r.error ?: "استجابة غير صالحة"}" } }
        }
    }

    private fun connectPhone() { if (PermissionCoordinator.isAccessibilityEnabled(this) && !PermissionCoordinator.isServiceLive()) { refreshConnectionState(); return }; PermissionCoordinator.openAccessibilitySettings(this); Toast.makeText(this, "فعّل Universal Creative Agent ثم ارجع إلى التطبيق.", Toast.LENGTH_LONG).show() }
    private fun chooseMedia() { startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply { type = "*/*"; putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true); addCategory(Intent.CATEGORY_OPENABLE) }, pickMedia) }
    private fun startSpeech() { try { startActivityForResult(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply { putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM); putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ar-SA"); putExtra(RecognizerIntent.EXTRA_PROMPT, "تحدث بطلبك") }, speech) } catch (_: Exception) { Toast.makeText(this, "التعرف الصوتي غير متاح على هذا الجهاز.", Toast.LENGTH_SHORT).show() } }
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) { super.onActivityResult(requestCode, resultCode, data); if (resultCode != RESULT_OK || data == null) return; if (requestCode == pickMedia) { data.clipData?.let { clip -> for (i in 0 until clip.itemCount) selectedMedia.add(clip.getItemAt(i).uri.toString()) } ?: data.data?.let { selectedMedia.add(it.toString()) }; input.hint = "أضفت ${selectedMedia.size} ملف — اكتب المطلوب" } else if (requestCode == speech) data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()?.let { input.setText(it) } }

    private fun analyzeTask() {
        latestTaskText = input.text.toString().trim(); if (latestTaskText.isEmpty()) return
        addUserBubble(latestTaskText + if (selectedMedia.isNotEmpty()) "\n📎 ${selectedMedia.size} ملف" else ""); input.setText("")
        val fallback = TaskInterpreter().analyze(latestTaskText, selectedMedia); latestPlan = fallback
        addAssistantBubble(if (brain.configured()) "أرسل المهمة إلى عقل AI لبناء الخطة العالمية…" else "عقل AI غير مُعد؛ سأعرض الخطة الاحتياطية. اضبط عقل AI قبل التنفيذ.")
        if (brain.configured()) brain.plan(latestTaskText, selectedMedia) { r -> runOnUiThread { val p = r.body; if (r.ok && p != null) { val steps = mutableListOf<String>(); p.optJSONArray("steps")?.let { a -> for (i in 0 until a.length()) steps += a.optString(i) }; if (steps.isNotEmpty()) latestPlan = fallback.copy(summary = p.optString("summary", fallback.summary), steps = steps) } else addAssistantBubble("تعذر بناء الخطة من العقل الآن: ${r.error ?: "خطأ غير معروف"}"); addPlanCard(latestPlan!!); if (selectedMedia.isNotEmpty()) queueBackgroundPreparation(latestTaskText) } } else { addPlanCard(latestPlan!!); if (selectedMedia.isNotEmpty()) queueBackgroundPreparation(latestTaskText) }
    }

    private fun queueBackgroundPreparation(task: String) { val data = Data.Builder().putString("task", task).putInt("media_count", selectedMedia.size).putStringArray("media_uris", selectedMedia.toTypedArray()).build(); WorkManager.getInstance(this).enqueue(OneTimeWorkRequestBuilder<MediaBackgroundWorker>().setInputData(data).build()) }
    private fun addAssistantBubble(text: String) = addBubble(text, false); private fun addUserBubble(text: String) = addBubble(text, true)
    private fun addBubble(text: String, user: Boolean) { val tv = TextView(this).apply { this.text = text; textSize = 16f; setTextColor(if (user) Color.WHITE else Color.DKGRAY); setPadding(18, 18, 18, 18); setBackgroundColor(if (user) 0xFF222222.toInt() else 0xFFF2F2F2.toInt()) }; chat.addView(tv, LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT).apply { setMargins(0, 0, 0, 16) }) }

    private fun addPlanCard(plan: TaskInterpreter.PlanResult) {
        latestPlan = plan; latestPlanCard?.let { chat.removeView(it) }
        val card = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(20, 18, 20, 18); setBackgroundColor(0xFFF7F7F7.toInt()) }
        val heading = TextView(this).apply { text = "خطة التنفيذ العالمية"; textSize = 18f; setTextColor(Color.BLACK) }
        val summary = TextView(this).apply { text = plan.summary; textSize = 14f; setPadding(0, 8, 0, 8) }
        val steps = TextView(this).apply { text = plan.steps.mapIndexed { i, s -> "${i + 1}. $s" }.joinToString("\n"); textSize = 15f; setPadding(0, 8, 0, 16) }
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val review = Button(this).apply { text = "مراجعة وتعديل"; setOnClickListener { showReview(latestPlan!!) } }
        val execute = Button(this).apply { text = "تنفيذ عالمي"; setOnClickListener { executePlan(card) } }
        row.addView(execute, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)); row.addView(review, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f); )
        card.addView(heading); card.addView(summary); card.addView(steps); card.addView(row); chat.addView(card, LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT).apply { setMargins(0, 0, 0, 16) }); latestPlanCard = card
    }

    private fun showReview(plan: TaskInterpreter.PlanResult) {
        val editor = EditText(this).apply { setText(plan.steps.mapIndexed { i, s -> "${i + 1}. $s" }.joinToString("\n")); minLines = 8 }
        AlertDialog.Builder(this).setTitle("تعديل الخطة العالمية").setView(editor).setNegativeButton("إلغاء", null).setPositiveButton("حفظ") { _, _ -> val steps = editor.text.toString().lines().map { it.trim() }.filter { it.isNotEmpty() }.map { it.replaceFirst(Regex("^\\d+\\.\\s*"), "") }; latestPlan = plan.copy(steps = steps); addPlanCard(latestPlan!!); addAssistantBubble("تم حفظ الخطة.") }.show()
    }

    private fun executePlan(card: View) {
        if (!PermissionCoordinator.isServiceLive()) { Toast.makeText(this, "فعّل ربط الهاتف أولًا.", Toast.LENGTH_LONG).show(); connectPhone(); return }
        if (!brain.configured()) { showBrainSettings(); return }
        val taskForAgent = latestTaskText + "\nالخطة المعتمدة من المستخدم:\n" + (latestPlan?.steps?.mapIndexed { i, s -> "${i + 1}. $s" }?.joinToString("\n") ?: "")
        card.isEnabled = false; addAssistantBubble("بدأ الوكيل العالمي: ملاحظة الشاشة ← قرار AI ← تنفيذ ← تحقق، مع تكرار الدورة حتى الإكمال أو الفشل الآمن.")
        UniversalAgentLoop(brain).start(taskForAgent, object : UniversalAgentLoop.Listener {
            override fun onEvent(text: String) { runOnUiThread { status.text = text.take(260); if (text.contains("—") || text.startsWith("العقل")) addAssistantBubble(text.take(900)) } }
            override fun onFinished(success: Boolean) { runOnUiThread { card.isEnabled = true; addAssistantBubble(if (success) "✅ أعلن العقل اكتمال المهمة بعد التحقق." else "⚠️ توقفت الدورة قبل إعلان الاكتمال. راجع آخر حالة في السجل.") } }
        })
    }
}
