package com.ucoa.app

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.speech.RecognizerIntent
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.work.Data
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager

class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var debugLog: TextView
    private lateinit var chat: LinearLayout
    private lateinit var input: EditText
    private lateinit var connectButton: Button
    private lateinit var brain: AgentBrainClient
    private var unsubscribeDiagnostics: (() -> Unit)? = null
    private val selectedMedia = mutableListOf<String>()
    private data class CloudPlan(val summary: String, val steps: List<String>, val taskType: String)
    private var latestPlan: CloudPlan? = null
    private var latestTaskText = ""
    private var latestPlanCard: View? = null
    private var smokePlanSeen = false
    private var smokeExecutionSeen = false
    private var smokeVerificationSeen = false
    private val pickMedia = 401
    private val speech = 402

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        UcoaDiagnostics.init(this)
        brain = AgentBrainClient(this)
        UcoaDiagnostics.log("APP", "بدأت MainActivity", "android=${android.os.Build.VERSION.SDK_INT} device=${android.os.Build.MODEL}")
        UcoaDiagnostics.log("CLOUD_BRAIN", "العقل السحابي", "models_and_providers=cloud_only")
        setContentView(buildUi())
        unsubscribeDiagnostics = UcoaDiagnostics.subscribe { _ ->
            runOnUiThread {
                debugLog.text = UcoaDiagnostics.recentText()
                debugLog.post { (debugLog.parent?.parent as? ScrollView)?.fullScroll(View.FOCUS_DOWN) }
            }
        }
        debugLog.text = UcoaDiagnostics.recentText()
        refreshConnectionState()
        intent.getStringExtra("smoke_task")?.trim()?.takeIf { it.isNotEmpty() }?.let { task ->
            UcoaDiagnostics.log("SMOKE", "استلمت أمر الاختبار", task)
            window.decorView.postDelayed({ input.setText(task); analyzeTask() }, 1200L)
        }
    }

    override fun onResume() { super.onResume(); if (::status.isInitialized) refreshConnectionState() }

    override fun onDestroy() {
        unsubscribeDiagnostics?.invoke(); unsubscribeDiagnostics = null
        super.onDestroy()
    }

    private fun buildUi(): View {
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(Color.WHITE) }
        val top = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(22, 26, 22, 10) }
        val title = TextView(this).apply { text = "Universal Creative Agent"; textSize = 21f; setTextColor(Color.BLACK); gravity = Gravity.CENTER_HORIZONTAL }
        status = TextView(this).apply { textSize = 13f; gravity = Gravity.CENTER_HORIZONTAL; setPadding(0, 8, 0, 8) }
        val settings = Button(this).apply { text = "إعداد عقل AI"; setOnClickListener { showBrainSettings() } }
        connectButton = Button(this).apply { text = "ربط الهاتف بنقرة واحدة"; setOnClickListener { connectPhone() } }
        val copyLog = Button(this).apply { text = "نسخ سجل التشخيص"; setOnClickListener { copyDiagnostics() } }
        val clearLog = Button(this).apply { text = "مسح السجل"; setOnClickListener { UcoaDiagnostics.clear(); debugLog.text = "" } }
        val debugHeader = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        debugHeader.addView(copyLog, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        debugHeader.addView(clearLog, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        top.addView(title); top.addView(status); top.addView(settings); top.addView(connectButton); top.addView(debugHeader)

        val debugScroll = ScrollView(this).apply { setBackgroundColor(0xFF111111.toInt()); layoutParams = LinearLayout.LayoutParams(-1, 0, 0.26f) }
        debugLog = TextView(this).apply { textSize = 11f; setTextColor(0xFFE8E8E8.toInt()); setPadding(14, 12, 14, 12); typeface = android.graphics.Typeface.MONOSPACE; text = "سجل التنفيذ الحي سيظهر هنا تلقائيًا…" }
        debugScroll.addView(debugLog); top.addView(debugScroll); root.addView(top)
        val scroll = ScrollView(this).apply { setFillViewport(true); layoutParams = LinearLayout.LayoutParams(-1, 0, 0.74f) }
        chat = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(22, 12, 22, 22) }
        addAssistantBubble("أنا جاهز. اكتب المهمة؛ سأطلب الخطة من Cloud Brain ثم أنتظر موافقتك قبل التنفيذ الحقيقي.")
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
        val enabled = PermissionCoordinator.isAccessibilityEnabled(this)
        val live = PermissionCoordinator.isServiceLive()
        val brainText = if (brain.configured()) " • عنوان Brain موجود" else " • Brain غير مهيأ"
        status.text = when { live -> "● الهاتف متصل — التحكم والمراقبة متاحان$brainText"; enabled -> "● الصلاحية مفعلة — جارٍ انتظار الخدمة$brainText"; else -> "○ غير متصل — فعّل الوصول مرة واحدة$brainText" }
        connectButton.text = when { live -> "الهاتف متصل"; enabled -> "إعادة فتح إعدادات الوصول"; else -> "ربط الهاتف بنقرة واحدة" }
        UcoaDiagnostics.log("STATE", "حالة الهاتف", "accessibility_enabled=$enabled service_live=$live brain_endpoint_configured=${brain.configured()}")
    }

    private fun showBrainSettings() {
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(18, 8, 18, 4) }
        val endpoint = EditText(this).apply { hint = "عنوان Brain API"; setSingleLine(); setText(brain.endpoint()) }
        val token = EditText(this).apply { hint = "رمز الوصول للخادم (اختياري)"; setSingleLine(); setText(brain.token()); inputType = 0x81 }
        box.addView(endpoint); box.addView(token)
        val dialog = AlertDialog.Builder(this).setTitle("ربط عقل AI العالمي").setView(box).setNegativeButton("إلغاء", null).setPositiveButton("حفظ") { _, _ -> brain.saveConfig(endpoint.text.toString(), token.text.toString()); UcoaDiagnostics.log("BRAIN_CONFIG", "تم حفظ إعدادات Brain", "endpoint=${endpoint.text}"); refreshConnectionState(); addAssistantBubble("تم حفظ اتصال عقل AI العالمي.") }.create()
        dialog.setButton(AlertDialog.BUTTON_NEUTRAL, "اختبار الاتصال") { _, _ -> }
        dialog.show()
        dialog.getButton(AlertDialog.BUTTON_NEUTRAL)?.setOnClickListener {
            brain.saveConfig(endpoint.text.toString(), token.text.toString()); status.text = "يجري اختبار اتصال عقل AI…"; UcoaDiagnostics.log("BRAIN_HEALTH", "بدأ اختبار Brain", "endpoint=${endpoint.text}")
            brain.health { ok, detail -> runOnUiThread { UcoaDiagnostics.log("BRAIN_HEALTH", if (ok) "انتهى اختبار Brain" else "فشل اختبار Brain", detail); status.text = if (ok) "● تم الوصول إلى خادم عقل AI — $detail" else "○ فشل الاتصال: $detail" } }
        }
    }

    private fun copyDiagnostics() { val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager; clipboard.setPrimaryClip(ClipData.newPlainText("UCOA diagnostics", UcoaDiagnostics.recentText())); Toast.makeText(this, "تم نسخ سجل التشخيص.", Toast.LENGTH_SHORT).show() }
    private fun connectPhone() { UcoaDiagnostics.log("ACCESSIBILITY", "فتح إعدادات الوصول"); PermissionCoordinator.openAccessibilitySettings(this); Toast.makeText(this, "فعّل Universal Creative Agent في خدمات الوصول ثم ارجع إلى التطبيق.", Toast.LENGTH_LONG).show() }
    private fun chooseMedia() { startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply { type = "*/*"; putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true); addCategory(Intent.CATEGORY_OPENABLE) }, pickMedia) }
    private fun startSpeech() { try { startActivityForResult(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply { putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM); putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ar-SA"); putExtra(RecognizerIntent.EXTRA_PROMPT, "تحدث بطلبك") }, speech) } catch (_: Exception) { UcoaDiagnostics.log("SPEECH", "التعرف الصوتي غير متاح"); Toast.makeText(this, "التعرف الصوتي غير متاح على هذا الجهاز.", Toast.LENGTH_SHORT).show() } }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data); if (resultCode != RESULT_OK || data == null) return
        if (requestCode == pickMedia) { data.clipData?.let { clip -> for (i in 0 until clip.itemCount) selectedMedia.add(clip.getItemAt(i).uri.toString()) } ?: data.data?.let { selectedMedia.add(it.toString()) }; UcoaDiagnostics.log("MEDIA", "تمت إضافة مرفقات", "count=${selectedMedia.size}"); input.hint = "أضفت ${selectedMedia.size} ملف — اكتب المطلوب" }
        else if (requestCode == speech) data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()?.let { input.setText(it) }
    }

    private fun analyzeTask() {
        latestTaskText = input.text.toString().trim(); if (latestTaskText.isEmpty()) return
        UcoaDiagnostics.log("TASK", "استلام مهمة", latestTaskText)
        addUserBubble(latestTaskText + if (selectedMedia.isNotEmpty()) "\n📎 ${selectedMedia.size} ملف" else "")
        input.setText("")
        requestCloudPlan()
    }

    private fun requestCloudPlan() {
        UcoaDiagnostics.log("ROUTER", "CLOUD_ONLY", "no_local_model_or_local_inference")
        UcoaDiagnostics.log("BRAIN_HEALTH", "فحص جاهزية Cloud Brain قبل التخطيط")
        brain.readiness { transportOk, ready, detail -> runOnUiThread {
            UcoaDiagnostics.log("BRAIN_HEALTH", "نتيجة فحص الجاهزية", "transport=$transportOk ready=$ready detail=$detail")
            if (!transportOk || !ready) { addAssistantBubble("Cloud Brain غير جاهز: $detail"); return@runOnUiThread }
            addAssistantBubble("Cloud Brain جاهز. أرسل المهمة إلى المخطط السحابي…")
            brain.plan(latestTaskText, selectedMedia) { r -> runOnUiThread {
                UcoaDiagnostics.log("PLANNER", if (r.ok) "استلمت خطة من Cloud Brain" else "فشل التخطيط من Cloud Brain", r.error ?: "ok")
                val p = r.body
                if (r.ok && p != null) {
                    val steps = mutableListOf<String>(); p.optJSONArray("steps")?.let { a -> for (i in 0 until a.length()) steps += a.optString(i) }
                    if (steps.isEmpty()) { addAssistantBubble("Cloud Brain أعاد نتيجة بلا خطوات تنفيذ."); return@runOnUiThread }
                    latestPlan = CloudPlan(p.optString("summary", "خطة سحابية جاهزة للتنفيذ"), steps, p.optString("task_type", "cloud"))
                    if (intent.getStringExtra("smoke_task")?.isNotBlank() == true) smokePlanSeen = true
                    addPlanCard(latestPlan!!)
                    if (selectedMedia.isNotEmpty()) queueBackgroundPreparation(latestTaskText)
                    addAssistantBubble("الخطة السحابية جاهزة. راجعها واضغط «تنفيذ عالمي» للموافقة وبدء التنفيذ الحقيقي.")
                } else addAssistantBubble("تعذر بناء الخطة من Cloud Brain: ${r.error ?: "خطأ غير معروف"}")
            } }
        } }
    }

    private fun queueBackgroundPreparation(task: String) { val data = Data.Builder().putString("task", task).putInt("media_count", selectedMedia.size).putStringArray("media_uris", selectedMedia.toTypedArray()).build(); WorkManager.getInstance(this).enqueue(OneTimeWorkRequestBuilder<MediaBackgroundWorker>().setInputData(data).build()); UcoaDiagnostics.log("MEDIA", "تمت جدولة تجهيز الوسائط", "count=${selectedMedia.size}") }
    private fun addAssistantBubble(text: String) = addBubble(text, false)
    private fun addUserBubble(text: String) = addBubble(text, true)
    private fun addBubble(text: String, user: Boolean) { val tv = TextView(this).apply { this.text = text; textSize = 16f; setTextColor(if (user) Color.WHITE else Color.DKGRAY); setPadding(18, 18, 18, 18); setBackgroundColor(if (user) 0xFF222222.toInt() else 0xFFF2F2F2.toInt()) }; chat.addView(tv, LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT).apply { setMargins(0, 0, 0, 16) }) }

    private fun addPlanCard(plan: CloudPlan) {
        latestPlan = plan; latestPlanCard?.let { chat.removeView(it) }
        val card = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(20, 18, 20, 18); setBackgroundColor(0xFFF7F7F7.toInt()) }
        val heading = TextView(this).apply { text = "خطة التنفيذ العالمية"; textSize = 18f; setTextColor(Color.BLACK) }
        val summary = TextView(this).apply { text = plan.summary; textSize = 14f; setPadding(0, 8, 0, 8) }
        val steps = TextView(this).apply { text = plan.steps.mapIndexed { i, s -> "${i + 1}. $s" }.joinToString("\n"); textSize = 15f; setPadding(0, 8, 0, 16) }
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val review = Button(this).apply { text = "مراجعة وتعديل"; setOnClickListener { showReview(latestPlan!!) } }
        val execute = Button(this).apply { text = "تنفيذ عالمي"; setOnClickListener { executePlan(card) } }
        row.addView(execute, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)); row.addView(review, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        card.addView(heading); card.addView(summary); card.addView(steps); card.addView(row); chat.addView(card, LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT).apply { setMargins(0, 0, 0, 16) }); latestPlanCard = card
    }

    private fun showReview(plan: CloudPlan) {
        val editor = EditText(this).apply { setText(plan.steps.mapIndexed { i, s -> "${i + 1}. $s" }.joinToString("\n")); minLines = 8 }
        AlertDialog.Builder(this).setTitle("تعديل الخطة العالمية").setView(editor).setNegativeButton("إلغاء", null).setPositiveButton("حفظ") { _, _ -> val steps = editor.text.toString().lines().map { it.trim() }.filter { it.isNotEmpty() }.map { it.replaceFirst(Regex("^\\d+\\.\\s*"), "") }; latestPlan = plan.copy(steps = steps); addPlanCard(latestPlan!!); UcoaDiagnostics.log("PLANNER", "تم تعديل الخطة يدويًا", "steps=${steps.size}"); addAssistantBubble("تم حفظ الخطة.") }.show()
    }

    private fun executePlan(card: View) {
        if (!PermissionCoordinator.isServiceLive()) { UcoaDiagnostics.log("EXECUTOR", "منع بدء الوكيل", "service_live=false"); Toast.makeText(this, "فعّل ربط الهاتف أولًا.", Toast.LENGTH_LONG).show(); connectPhone(); return }
        UcoaDiagnostics.log("APPROVAL", "تم اعتماد الخطة من واجهة المستخدم", "task=$latestTaskText")
        UcoaDiagnostics.log("EXECUTOR", "بدء دورة الوكيل العالمي", "task=$latestTaskText cloud_brain=required")
        card.isEnabled = false; addAssistantBubble("بدأ الوكيل العالمي السحابي: ملاحظة الشاشة ← قرار Cloud AI ← تنفيذ ← تحقق.")
        UniversalAgentLoop(brain).start(latestTaskText + "\\nالخطة المعتمدة: " + (latestPlan?.steps?.mapIndexed { i, s -> "${i + 1}. $s" }?.joinToString("\\n") ?: ""), object : UniversalAgentLoop.Listener {
            override fun onEvent(text: String) { runOnUiThread { UcoaDiagnostics.log("AGENT", text); if (smokePlanSeen && text.startsWith("التنفيذ")) smokeExecutionSeen = true; if (smokePlanSeen && text.startsWith("التحقق")) smokeVerificationSeen = true; status.text = text.take(260); if (text.contains("—") || text.startsWith("العقل") || text.startsWith("التنفيذ") || text.startsWith("التحقق")) addAssistantBubble(text.take(900)) } }
            override fun onFinished(success: Boolean) { runOnUiThread { card.isEnabled = true; UcoaDiagnostics.log("AGENT", if (success) "انتهت دورة الوكيل بنجاح" else "انتهت دورة الوكيل بفشل", "success=$success"); if (smokePlanSeen) { val foreground = UcoaAccessibilityService.instance?.foregroundPackageName().orEmpty(); val realSmokeOk = success && smokeExecutionSeen && smokeVerificationSeen && foreground == "com.android.settings"; UcoaDiagnostics.log("UCOA_REAL_SMOKE", if (realSmokeOk) "UCOA_REAL_SMOKE_OK: plan + approval + execution + accessibility + foreground verification passed" else "UCOA_REAL_SMOKE_FAILED", "success=$success execution=$smokeExecutionSeen verification=$smokeVerificationSeen foreground=$foreground accessibility=${PermissionCoordinator.isServiceLive()}"); if (realSmokeOk) Log.i("UCOA_SMOKE", "UCOA_REAL_SMOKE_OK") }; addAssistantBubble(if (success) "✅ اكتملت المهمة بعد التحقق." else "⚠️ توقفت الدورة قبل إثبات الاكتمال. راجع سجل التشخيص أعلاه.") } }
        }, selectedMedia.toList())
    }
}
