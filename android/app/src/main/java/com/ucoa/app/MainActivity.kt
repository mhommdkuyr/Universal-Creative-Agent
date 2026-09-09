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
    private lateinit var localBrain: LocalBrainClient
    private var unsubscribeDiagnostics: (() -> Unit)? = null
    private val selectedMedia = mutableListOf<String>()
    private var latestPlan: TaskInterpreter.PlanResult? = null
    private var latestTaskText = ""
    private var latestPlanCard: View? = null
    private val pickMedia = 401
    private val speech = 402

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        UcoaDiagnostics.init(this)
        brain = AgentBrainClient(this)
        localBrain = LocalBrainClient(this)
        UcoaDiagnostics.log("APP", "بدأت MainActivity", "android=${android.os.Build.VERSION.SDK_INT} device=${android.os.Build.MODEL}")
        UcoaDiagnostics.log("LOCAL_BRAIN", "العقل المحلي", "bundled=${localBrain.isBundled()} model=Qwen3-0.6B-LiteRT")
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

    override fun onResume() {
        super.onResume()
        if (::status.isInitialized) refreshConnectionState()
    }

    override fun onDestroy() {
        unsubscribeDiagnostics?.invoke()
        unsubscribeDiagnostics = null
        if (::localBrain.isInitialized) localBrain.close()
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

        val debugScroll = ScrollView(this).apply {
            setBackgroundColor(0xFF111111.toInt())
            layoutParams = LinearLayout.LayoutParams(-1, 0, 0.26f)
        }
        debugLog = TextView(this).apply {
            textSize = 11f
            setTextColor(0xFFE8E8E8.toInt())
            setPadding(14, 12, 14, 12)
            typeface = android.graphics.Typeface.MONOSPACE
            text = "سجل التنفيذ الحي سيظهر هنا تلقائيًا…"
        }
        debugScroll.addView(debugLog)
        top.addView(debugScroll)
        root.addView(top)

        val scroll = ScrollView(this).apply { setFillViewport(true); layoutParams = LinearLayout.LayoutParams(-1, 0, 0.74f) }
        chat = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(22, 12, 22, 22) }
        addAssistantBubble("أنا جاهز. اكتب المهمة وسأبني الخطة ثم أنفذها تلقائيًا بعد التحقق من صلاحية التحكم.")
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
        status.text = when {
            live -> "● الهاتف متصل — التحكم والمراقبة متاحان$brainText"
            enabled -> "● الصلاحية مفعلة — جارٍ انتظار الخدمة$brainText"
            else -> "○ غير متصل — فعّل الوصول مرة واحدة$brainText"
        }
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
            brain.saveConfig(endpoint.text.toString(), token.text.toString())
            status.text = "يجري اختبار اتصال عقل AI…"
            UcoaDiagnostics.log("BRAIN_HEALTH", "بدأ اختبار Brain", "endpoint=${endpoint.text}")
            brain.health { ok, detail -> runOnUiThread {
                UcoaDiagnostics.log("BRAIN_HEALTH", if (ok) "انتهى اختبار Brain" else "فشل اختبار Brain", detail)
                status.text = if (ok) "● تم الوصول إلى خادم عقل AI — $detail" else "○ فشل الاتصال: $detail"
            } }
        }
    }

    private fun copyDiagnostics() {
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("UCOA diagnostics", UcoaDiagnostics.recentText()))
        Toast.makeText(this, "تم نسخ سجل التشخيص.", Toast.LENGTH_SHORT).show()
    }

    private fun connectPhone() {
        UcoaDiagnostics.log("ACCESSIBILITY", "فتح إعدادات الوصول")
        PermissionCoordinator.openAccessibilitySettings(this)
        Toast.makeText(this, "فعّل Universal Creative Agent في خدمات الوصول ثم ارجع إلى التطبيق.", Toast.LENGTH_LONG).show()
    }

    private fun chooseMedia() { startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply { type = "*/*"; putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true); addCategory(Intent.CATEGORY_OPENABLE) }, pickMedia) }

    private fun startSpeech() { try { startActivityForResult(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply { putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM); putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ar-SA"); putExtra(RecognizerIntent.EXTRA_PROMPT, "تحدث بطلبك") }, speech) } catch (_: Exception) { UcoaDiagnostics.log("SPEECH", "التعرف الصوتي غير متاح"); Toast.makeText(this, "التعرف الصوتي غير متاح على هذا الجهاز.", Toast.LENGTH_SHORT).show() } }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != RESULT_OK || data == null) return
        if (requestCode == pickMedia) {
            data.clipData?.let { clip -> for (i in 0 until clip.itemCount) selectedMedia.add(clip.getItemAt(i).uri.toString()) } ?: data.data?.let { selectedMedia.add(it.toString()) }
            UcoaDiagnostics.log("MEDIA", "تمت إضافة مرفقات", "count=${selectedMedia.size}")
            input.hint = "أضفت ${selectedMedia.size} ملف — اكتب المطلوب"
        } else if (requestCode == speech) data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()?.let { input.setText(it) }
    }

    private fun analyzeTask() {
        latestTaskText = input.text.toString().trim(); if (latestTaskText.isEmpty()) return
        UcoaDiagnostics.log("TASK", "استلام مهمة", latestTaskText)
        addUserBubble(latestTaskText + if (selectedMedia.isNotEmpty()) "\n📎 ${selectedMedia.size} ملف" else "")
        input.setText("")
        val fallback = TaskInterpreter().analyze(latestTaskText, selectedMedia); latestPlan = fallback
        UcoaDiagnostics.log("PLANNER", "الخطة المحلية الأولية جاهزة", "steps=${fallback.steps.size}")
        routeThroughLocalBrain(fallback)
    }

    private fun routeThroughLocalBrain(fallback: TaskInterpreter.PlanResult) {
        addAssistantBubble("أفحص العقل المحلي أولًا…")
        val apps = AppDiscovery.installedLabels(this)
        UcoaDiagnostics.log("LOCAL_BRAIN", "بدء التصنيف المحلي", "apps=${apps.size} task=$latestTaskText")
        localBrain.classify(latestTaskText, apps) { result ->
            runOnUiThread {
                UcoaDiagnostics.log("LOCAL_BRAIN", if (result.understood) "العقل المحلي فهم المهمة" else "العقل المحلي لم يفهم المهمة — تحويل للسحابة", "action=${result.action} app=${result.app} confidence=${result.confidence} error=${result.error ?: "none"}")
                if (result.understood && result.action == "open_app" && !result.app.isNullOrBlank()) {
                    addAssistantBubble("العقل المحلي فهم الأمر. سأفتحه محليًا بدون إرسال المهمة إلى السحابة.")
                    addPlanCard(fallback.copy(summary = "تنفيذ محلي بواسطة العقل الموجود داخل التطبيق", steps = listOf("فتح ${result.app}")))
                    executeLocalApp(result.app)
                    return@runOnUiThread
                }
                if (intent.getBooleanExtra("smoke_local_only", false)) {
                    addAssistantBubble("اختبار محلي: لم ينتج العقل المحلي إجراءً صالحًا، سأستخدم منفذ الأوامر المحلي كاختبار تحكم احتياطي.")
                    addPlanCard(fallback); autoExecuteLocal(); return@runOnUiThread
                }
                continueCloudRoute(fallback)
            }
        }
    }

    private fun continueCloudRoute(fallback: TaskInterpreter.PlanResult) {
        addAssistantBubble("المهمة خارج نطاق العقل المحلي؛ أحولها الآن إلى Cloud Brain.")
        UcoaDiagnostics.log("ROUTER", "LOCAL→CLOUD", "reason=local_brain_no_action")
        UcoaDiagnostics.log("BRAIN_HEALTH", "فحص جاهزية Brain قبل التخطيط")
        brain.readiness { transportOk, ready, detail -> runOnUiThread {
            UcoaDiagnostics.log("BRAIN_HEALTH", "نتيجة فحص الجاهزية", "transport=$transportOk ready=$ready detail=$detail")
            if (!transportOk || !ready) {
                addAssistantBubble("Cloud Brain غير جاهز: $detail")
                addPlanCard(fallback); autoExecuteLocal()
                if (selectedMedia.isNotEmpty()) queueBackgroundPreparation(latestTaskText)
                return@runOnUiThread
            }
            addAssistantBubble("Cloud Brain جاهز. أرسل المهمة إلى المخطط…")
            brain.plan(latestTaskText, selectedMedia) { r -> runOnUiThread {
                UcoaDiagnostics.log("PLANNER", if (r.ok) "استلمت خطة من Cloud Brain" else "فشل التخطيط من Cloud Brain", r.error ?: "ok")
                val p = r.body
                if (r.ok && p != null) {
                    val steps = mutableListOf<String>(); p.optJSONArray("steps")?.let { a -> for (i in 0 until a.length()) steps += a.optString(i) }
                    if (steps.isNotEmpty()) latestPlan = fallback.copy(summary = p.optString("summary", fallback.summary), steps = steps)
                    addPlanCard(latestPlan!!)
                    if (selectedMedia.isNotEmpty()) queueBackgroundPreparation(latestTaskText)
                    addAssistantBubble("الخطة السحابية جاهزة. بدء التنفيذ تلقائيًا…")
                    executePlan(latestPlanCard!!)
                } else {
                    addAssistantBubble("تعذر بناء الخطة من Cloud Brain: ${r.error ?: "خطأ غير معروف"}")
                    addPlanCard(latestPlan!!); autoExecuteLocal()
                }
            } }
        } }
    }

    private fun executeLocalApp(app: String) {
        val service = UcoaAccessibilityService.instance
        if (service == null) {
            UcoaDiagnostics.log("EXECUTOR", "فشل التنفيذ المحلي", "accessibility_service_live=false")
            addAssistantBubble("❌ خدمة التحكم غير متصلة. فعّل صلاحية الوصول ثم أعد المحاولة.")
            connectPhone(); return
        }
        UcoaDiagnostics.log("EXECUTOR", "تنفيذ قرار العقل المحلي", "action=open_app requested=$app before=${service.foregroundPackageName()}")
        val ok = service.openAppByName(app)
        UcoaDiagnostics.log("EXECUTOR", if (ok) "تم إرسال أمر فتح التطبيق" else "فشل إرسال أمر فتح التطبيق", "requested=$app foreground_now=${service.foregroundPackageName()}")
        if (ok) Log.i("UCOA_SMOKE", "UCOA_LOCAL_EXECUTION_OK app=$app")
        verifyForegroundAfterOpen(app)
    }

    private fun autoExecuteLocal() {
        val service = UcoaAccessibilityService.instance
        if (service == null) {
            UcoaDiagnostics.log("EXECUTOR", "فشل التنفيذ المحلي", "accessibility_service_live=false")
            addAssistantBubble("❌ خدمة التحكم غير متصلة. فعّل صلاحية الوصول ثم أعد المحاولة.")
            connectPhone(); return
        }
        val app = Regex("(?:افتح|فتح|شغل|شغّل)\\s+(واتساب|whatsapp|يوتيوب|youtube|كاب ?كات|capcut|كانفا|canva|كروم|chrome|انستجرام|instagram|تليجرام|telegram|الإعدادات|اعدادات|settings|الضبط)", RegexOption.IGNORE_CASE).find(latestTaskText)?.groupValues?.getOrNull(1)
        if (app != null) executeLocalApp(app) else {
            UcoaDiagnostics.log("EXECUTOR", "لا يوجد منفذ محلي لهذه المهمة", "brain_required=true")
            addAssistantBubble("المهمة تحتاج Cloud Brain؛ لم أنفذ إجراءً غير محدد محليًا.")
        }
    }

    private fun verifyForegroundAfterOpen(requested: String) {
        val service = UcoaAccessibilityService.instance ?: return
        val expected = service.packageForName(requested)
        if (expected == null) {
            UcoaDiagnostics.log("VERIFY", "لا يمكن تحديد package المتوقع", "requested=$requested")
            addAssistantBubble("⚠️ تم إرسال أمر الفتح لكن لم أستطع تحديد الحزمة المتوقعة للتحقق.")
            return
        }
        val started = System.currentTimeMillis()
        fun poll(attempt: Int) {
            val actual = service.foregroundPackageName()
            UcoaDiagnostics.log("VERIFY", "فحص التطبيق الأمامي", "expected=$expected actual=$actual attempt=$attempt")
            if (actual == expected) {
                addAssistantBubble("✅ تم فتح $requested والتحقق من ظهوره فعليًا على الشاشة.")
                UcoaDiagnostics.log("VERIFY", "نجح التحقق النهائي", "package=$expected elapsed_ms=${System.currentTimeMillis() - started}")
            } else if (attempt < 20) window.decorView.postDelayed({ poll(attempt + 1) }, 250L)
            else {
                addAssistantBubble("❌ أمر الفتح أُرسل لكن التحقق لم يثبت ظهور $requested. آخر package=$actual")
                UcoaDiagnostics.log("VERIFY", "فشل التحقق النهائي", "expected=$expected actual=$actual elapsed_ms=${System.currentTimeMillis() - started}")
            }
        }
        poll(0)
    }

    private fun queueBackgroundPreparation(task: String) {
        val data = Data.Builder().putString("task", task).putInt("media_count", selectedMedia.size).putStringArray("media_uris", selectedMedia.toTypedArray()).build()
        WorkManager.getInstance(this).enqueue(OneTimeWorkRequestBuilder<MediaBackgroundWorker>().setInputData(data).build())
        UcoaDiagnostics.log("MEDIA", "تمت جدولة تجهيز الوسائط", "count=${selectedMedia.size}")
    }

    private fun addAssistantBubble(text: String) = addBubble(text, false)
    private fun addUserBubble(text: String) = addBubble(text, true)
    private fun addBubble(text: String, user: Boolean) {
        val tv = TextView(this).apply { this.text = text; textSize = 16f; setTextColor(if (user) Color.WHITE else Color.DKGRAY); setPadding(18, 18, 18, 18); setBackgroundColor(if (user) 0xFF222222.toInt() else 0xFFF2F2F2.toInt()) }
        chat.addView(tv, LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT).apply { setMargins(0, 0, 0, 16) })
    }

    private fun addPlanCard(plan: TaskInterpreter.PlanResult) {
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

    private fun showReview(plan: TaskInterpreter.PlanResult) {
        val editor = EditText(this).apply { setText(plan.steps.mapIndexed { i, s -> "${i + 1}. $s" }.joinToString("\n")); minLines = 8 }
        AlertDialog.Builder(this).setTitle("تعديل الخطة العالمية").setView(editor).setNegativeButton("إلغاء", null).setPositiveButton("حفظ") { _, _ -> val steps = editor.text.toString().lines().map { it.trim() }.filter { it.isNotEmpty() }.map { it.replaceFirst(Regex("^\\d+\\.\\s*"), "") }; latestPlan = plan.copy(steps = steps); addPlanCard(latestPlan!!); UcoaDiagnostics.log("PLANNER", "تم تعديل الخطة يدويًا", "steps=${steps.size}"); addAssistantBubble("تم حفظ الخطة.") }.show()
    }

    private fun executePlan(card: View) {
        if (!PermissionCoordinator.isServiceLive()) { UcoaDiagnostics.log("EXECUTOR", "منع بدء الوكيل", "service_live=false"); Toast.makeText(this, "فعّل ربط الهاتف أولًا.", Toast.LENGTH_LONG).show(); connectPhone(); return }
        UcoaDiagnostics.log("EXECUTOR", "بدء دورة الوكيل العالمي", "task=$latestTaskText")
        card.isEnabled = false; addAssistantBubble("بدأ الوكيل العالمي: ملاحظة الشاشة ← قرار AI ← تنفيذ ← تحقق.")
        UniversalAgentLoop(brain).start(latestTaskText + "\\nالخطة المعتمدة: " + (latestPlan?.steps?.mapIndexed { i, s -> "${i + 1}. $s" }?.joinToString("\\n") ?: ""), object : UniversalAgentLoop.Listener {
            override fun onEvent(text: String) {
                runOnUiThread {
                    UcoaDiagnostics.log("AGENT", text)
                    status.text = text.take(260)
                    if (text.contains("—") || text.startsWith("العقل") || text.startsWith("التنفيذ") || text.startsWith("التحقق")) addAssistantBubble(text.take(900))
                }
            }
            override fun onFinished(success: Boolean) {
                runOnUiThread {
                    card.isEnabled = true
                    UcoaDiagnostics.log("AGENT", if (success) "انتهت دورة الوكيل بنجاح" else "انتهت دورة الوكيل بفشل", "success=$success")
                    addAssistantBubble(if (success) "✅ اكتملت المهمة بعد التحقق." else "⚠️ توقفت الدورة قبل إثبات الاكتمال. راجع سجل التشخيص أعلاه.")
                }
            }
        }, selectedMedia.toList())
    }
}
