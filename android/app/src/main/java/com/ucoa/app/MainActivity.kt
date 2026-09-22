package com.ucoa.app

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.speech.RecognizerIntent
import android.util.Base64
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.*
import java.util.UUID

class MainActivity : Activity() {
    private lateinit var root: FrameLayout
    private lateinit var chat: LinearLayout
    private lateinit var input: EditText
    private lateinit var status: TextView
    private lateinit var menuButton: TextView
    private lateinit var drawer: LinearLayout
    private lateinit var drawerScrim: View
    private lateinit var brain: AgentBrainClient
    private var liveCard: LiveExecutionCard? = null
    private var unsubscribeDiagnostics: (() -> Unit)? = null
    private var unsubscribeLive: (() -> Unit)? = null
    private val selectedMedia = mutableListOf<String>()
    private var latestTaskText = ""
    private var conversationStarted = false
    private var executionSubmitted = false
    private var planningInProgress = false
    private var currentConversationTitle = "محادثة جديدة"
    private val pickMedia = 401
    private val speech = 402

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.BLACK
        window.navigationBarColor = Color.BLACK
        brain = AgentBrainClient(this)
        UcoaDiagnostics.init(this)
        setContentView(buildUi())
        unsubscribeLive = LiveExecutionState.subscribe { snap -> runOnUiThread { renderLive(snap) } }
        unsubscribeDiagnostics = UcoaDiagnostics.subscribe { event -> runOnUiThread { if (event.stage == "REMOTE_BRIDGE" || event.stage == "AGENT" || event.stage == "EXECUTOR") status.text = event.message } }
        refreshConnectionState()
        intent.getStringExtra("smoke_task")?.trim()?.takeIf { it.isNotEmpty() }?.let { task -> window.decorView.postDelayed({ input.setText(task); analyzeTask() }, 900L) }
    }
    override fun onResume() { super.onResume(); if (::status.isInitialized) refreshConnectionState() }
    override fun onDestroy() { unsubscribeDiagnostics?.invoke(); unsubscribeLive?.invoke(); super.onDestroy() }

    private fun buildUi(): View {
        root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK); layoutDirection = View.LAYOUT_DIRECTION_RTL }
        val main = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(Color.BLACK) }
        val top = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(18, 12, 18, 10) }
        top.addView(iconButton("☰", "المحادثات") { toggleDrawer(true) }, LinearLayout.LayoutParams(54, 54))
        val plus = TextView(this).apply { text = "✦ الحصول على Plus"; textSize = 15f; typeface = Typeface.DEFAULT_BOLD; setTextColor(0xFFBFE4FF.toInt()); gravity = Gravity.CENTER; background = rounded(0xFF26313B.toInt(), 70f); setPadding(20, 10, 20, 10) }
        top.addView(plus, LinearLayout.LayoutParams(0, 54, 1f).apply { setMargins(18, 0, 18, 0) })
        menuButton = iconButton("◌", "محادثة جديدة") { if (!conversationStarted) startNewConversation() else showConversationMenu() }
        top.addView(menuButton, LinearLayout.LayoutParams(54, 54)); main.addView(top)
        status = TextView(this).apply { textSize = 11f; setTextColor(0xFF9AA3AE.toInt()); gravity = Gravity.CENTER; setPadding(8, 2, 8, 4) }; main.addView(status, LinearLayout.LayoutParams(-1, 28))
        val scroll = ScrollView(this).apply { setFillViewport(true); isVerticalScrollBarEnabled = false; layoutParams = LinearLayout.LayoutParams(-1, 0, 1f) }
        chat = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL; setPadding(16, 12, 16, 22) }; addAssistantBubble("اكتب ما تريد، وسأخطط له سحابيًا ثم أنفذه مرة واحدة مع تحقق حي من النتيجة."); scroll.addView(chat); main.addView(scroll)
        val composer = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(12, 8, 12, 12); background = rounded(0xFF17191D.toInt(), 28f) }
        composer.addView(iconButton("＋", "إضافة ملف") { chooseMedia() }, LinearLayout.LayoutParams(44, 52)); composer.addView(iconButton("⌕", "الصوت") { startSpeech() }, LinearLayout.LayoutParams(44, 52))
        input = EditText(this).apply { hint = "اكتب ما تريد تنفيذه…"; setHintTextColor(0xFF7E858F.toInt()); setTextColor(Color.WHITE); textSize = 16f; background = null; maxLines = 5; minLines = 1; gravity = Gravity.CENTER_VERTICAL; setPadding(12, 6, 12, 6) }
        composer.addView(input, LinearLayout.LayoutParams(0, 56, 1f)); composer.addView(iconButton("↑", "إرسال") { analyzeTask() }, LinearLayout.LayoutParams(50, 52)); main.addView(composer, LinearLayout.LayoutParams(-1, 78)); root.addView(main)
        drawerScrim = View(this).apply { setBackgroundColor(0x99000000.toInt()); visibility = View.GONE; setOnClickListener { toggleDrawer(false) } }; root.addView(drawerScrim, FrameLayout.LayoutParams(-1, -1))
        drawer = buildDrawer(); root.addView(drawer, FrameLayout.LayoutParams((resources.displayMetrics.widthPixels * 0.74f).toInt(), -1, Gravity.END)); return root
    }

    private fun buildDrawer(): LinearLayout {
        val panel = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(0xFF151619.toInt()); setPadding(18, 24, 18, 18) }
        panel.addView(TextView(this).apply { text = "محادثاتك"; textSize = 22f; typeface = Typeface.DEFAULT_BOLD; setTextColor(Color.WHITE); gravity = Gravity.RIGHT; setPadding(0, 4, 0, 18) })
        panel.addView(drawerAction("＋  محادثة جديدة") { startNewConversation(); toggleDrawer(false) }); panel.addView(drawerAction("⌕  البحث في المحادثات") { showSearchDialog() }); panel.addView(drawerAction("▣  التطبيقات المتصلة") { showConnectedApps() })
        panel.addView(Space(this), LinearLayout.LayoutParams(1, 24)); panel.addView(View(this).apply { setBackgroundColor(0xFF2A2D31.toInt()) }, LinearLayout.LayoutParams(-1, 1))
        val list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(0, 16, 0, 16) }
        listOf("محادثة جديدة", "اختبار تنفيذ الأوامر", "تصميم واجهة UCOA", "ربط الهاتف بالسحابة", "مراجعة التطبيق", "اختبارات Android").forEach { title -> list.addView(TextView(this).apply { text = title; textSize = 15f; setTextColor(0xFFD9DDE3.toInt()); gravity = Gravity.RIGHT or Gravity.CENTER_VERTICAL; setPadding(14, 16, 14, 16); setOnClickListener { currentConversationTitle = title; toggleDrawer(false); addAssistantBubble("تم فتح «$title». تفاصيل المحادثة محفوظة في هذه الجلسة.") } }, LinearLayout.LayoutParams(-1, 52)) }
        panel.addView(ScrollView(this).apply { isFillViewport = true; addView(list) }, LinearLayout.LayoutParams(-1, 0, 1f)); panel.addView(drawerAction("⚙  الإعدادات") { showSettingsPage() }); return panel
    }
    private fun drawerAction(label: String, click: () -> Unit) = TextView(this).apply { text = label; textSize = 16f; setTextColor(Color.WHITE); gravity = Gravity.RIGHT or Gravity.CENTER_VERTICAL; setPadding(16, 15, 16, 15); background = rounded(0xFF202226.toInt(), 18f); setOnClickListener { click() }; layoutParams = LinearLayout.LayoutParams(-1, 54).apply { setMargins(0, 5, 0, 5) } }

    private fun startNewConversation() { conversationStarted = false; executionSubmitted = false; planningInProgress = false; currentConversationTitle = "محادثة جديدة"; latestTaskText = ""; selectedMedia.clear(); chat.removeAllViews(); addAssistantBubble("محادثة جديدة. هذه المساحة للمحادثة والتخطيط؛ التنفيذ يبدأ فقط بعد اعتماد المهمة."); menuButton.text = "◌"; menuButton.contentDescription = "محادثة جديدة" }
    private fun showConversationMenu() = AlertDialog.Builder(this).setTitle("إعدادات المحادثة").setItems(arrayOf("مشاركة", "حذف", "تثبيت", "أرشفة", "البحث في المحادثة")) { _, which -> addAssistantBubble("تم اختيار: ${arrayOf("مشاركة", "حذف", "تثبيت", "أرشفة", "البحث في المحادثة")[which]}.") }.show()
    private fun showSearchDialog() { val q = EditText(this).apply { hint = "ابحث في محادثاتك"; setTextColor(Color.WHITE); setHintTextColor(0xFF888C93.toInt()) }; AlertDialog.Builder(this).setTitle("البحث في المحادثات").setView(q).setPositiveButton("بحث") { _, _ -> addAssistantBubble("نتائج البحث عن: ${q.text}"); toggleDrawer(false) }.setNegativeButton("إلغاء", null).show() }
    private fun showConnectedApps() { val apps = UcoaAccessibilityService.instance?.installedAppLabels()?.take(30)?.joinToString("\n") ?: "فعّل خدمة الوصول أولًا لقراءة التطبيقات المثبتة."; AlertDialog.Builder(this).setTitle("التطبيقات المتصلة").setMessage(apps).setPositiveButton("حسنًا", null).show() }

    private fun showSettingsPage() {
        val page = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(24, 24, 24, 24); setBackgroundColor(0xFF101114.toInt()) }
        page.addView(TextView(this).apply { text = "الإعدادات"; textSize = 24f; typeface = Typeface.DEFAULT_BOLD; setTextColor(Color.WHITE); setPadding(0, 8, 0, 24) })
        page.addView(settingRow("عقل AI السحابي", "المزودات والنماذج سحابية فقط") { showBrainSettings() }); page.addView(settingRow("الوصول والتنفيذ", "Accessibility + مراقبة الحالة") { connectPhone() }); page.addView(settingRow("المظهر", "الوضع الداكن، اللغة، كثافة الواجهة") { Toast.makeText(this, "إعدادات المظهر جاهزة للتخصيص.", Toast.LENGTH_SHORT).show() }); page.addView(settingRow("الخصوصية", "السجل، لقطات الشاشة، القياس") { Toast.makeText(this, "البيانات الحساسة لا تظهر في سجل التشخيص.", Toast.LENGTH_SHORT).show() }); page.addView(settingRow("التشخيص", "عرض سجل التنفيذ") { showDiagnostics() })
        page.addView(Button(this).apply { text = "إغلاق"; setOnClickListener { setContentView(buildUi()) } }, LinearLayout.LayoutParams(-1, 54).apply { setMargins(0, 20, 0, 0) }); setContentView(page)
    }
    private fun settingRow(titleText: String, sub: String, click: () -> Unit): View = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(16, 14, 16, 14); background = rounded(0xFF1D1F23.toInt(), 18f); setOnClickListener { click() }; addView(TextView(this@MainActivity).apply { text = titleText; textSize = 17f; typeface = Typeface.DEFAULT_BOLD; setTextColor(Color.WHITE) }); addView(TextView(this@MainActivity).apply { text = sub; textSize = 12f; setTextColor(0xFF9EA5AF.toInt()); setPadding(0, 5, 0, 0) }); layoutParams = LinearLayout.LayoutParams(-1, 78).apply { setMargins(0, 0, 0, 10) } }

    private fun renderLive(s: LiveExecutionState.Snapshot) {
        if (!s.active && s.task.isBlank()) return
        if (liveCard == null) { liveCard = LiveExecutionCard(this); chat.addView(liveCard, LinearLayout.LayoutParams(-1, 430).apply { setMargins(0, 8, 0, 18) }) }
        liveCard?.render(s)
    }
    private fun refreshConnectionState() { val enabled = PermissionCoordinator.isAccessibilityEnabled(this); val live = PermissionCoordinator.isServiceLive(); status.text = when { live -> "● متصل — تنفيذ ومراقبة سحابية"; enabled -> "● الصلاحية مفعلة — الخدمة قيد الاتصال"; else -> "○ فعّل الوصول من الإعدادات لبدء التنفيذ" } }

    private fun analyzeTask() {
        val task = input.text.toString().trim(); if (task.isEmpty() || planningInProgress) return
        latestTaskText = task; conversationStarted = true; executionSubmitted = false; planningInProgress = true; menuButton.text = "⋮"; menuButton.contentDescription = "إعدادات المحادثة"; currentConversationTitle = task.take(40)
        addUserBubble(task + if (selectedMedia.isNotEmpty()) "\n📎 ${selectedMedia.size} ملف" else ""); input.setText("")
        brain.readiness { transportOk, ready, detail -> runOnUiThread {
            if (!transportOk || !ready) { planningInProgress = false; addAssistantBubble("تعذر الوصول إلى Cloud Brain: $detail"); return@runOnUiThread }
            addAssistantBubble("أخطط للمهمة سحابيًا…")
            brain.plan(task, selectedMedia) { r -> runOnUiThread {
                if (!r.ok || r.body == null) { planningInProgress = false; addAssistantBubble("تعذر التخطيط: ${r.error ?: "خطأ غير معروف"}"); return@runOnUiThread }
                val steps = mutableListOf<String>(); r.body?.optJSONArray("steps")?.let { a -> for (i in 0 until a.length()) steps += a.optString(i) }
                if (steps.isEmpty()) { planningInProgress = false; addAssistantBubble("الخطة السحابية لم تُرجع خطوات."); return@runOnUiThread }
                planningInProgress = false; addPlanCard(r.body!!.optString("summary", "خطة سحابية جاهزة"), steps)
            } }
        } }
    }

    private fun addPlanCard(summary: String, steps: List<String>) {
        val executionKey = UUID.randomUUID().toString()
        val card = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(18, 16, 18, 16); background = rounded(0xFF1A1C20.toInt(), 24f) }
        card.addView(TextView(this).apply { text = "خطة التنفيذ"; textSize = 18f; typeface = Typeface.DEFAULT_BOLD; setTextColor(Color.WHITE) })
        card.addView(TextView(this).apply { text = summary; textSize = 13f; setTextColor(0xFFB8BEC8.toInt()); setPadding(0, 7, 0, 8) })
        card.addView(TextView(this).apply { text = steps.mapIndexed { i, x -> "${i + 1}. $x" }.joinToString("\n"); textSize = 14f; setTextColor(0xFFE5E7EB.toInt()); setPadding(0, 4, 0, 14) })
        card.addView(Button(this).apply {
            text = "تنفيذ مرة واحدة"
            setOnClickListener {
                if (executionSubmitted) return@setOnClickListener
                if (!PermissionCoordinator.isServiceLive()) { connectPhone(); return@setOnClickListener }
                executionSubmitted = true
                isEnabled = false
                addAssistantBubble("تمت الموافقة. أرسل المهمة إلى جسر الهاتف السحابي؛ التنفيذ سيظهر هنا حيًا.")
                brain.queueTask(latestTaskText, selectedMedia, JSONObject().put("ui", "conversation_live").put("evidence_required", true).put("idempotency_key", executionKey)) { r -> runOnUiThread { if (r.ok) { LiveExecutionState.begin(latestTaskText); addAssistantBubble("✓ تم تسليم المهمة للجهاز. التنفيذ الوحيد لهذه الموافقة جارٍ الآن.") } else { executionSubmitted = false; isEnabled = true; addAssistantBubble("تعذر تسليم المهمة للجسر السحابي: ${r.error ?: "خطأ غير معروف"}") } } }
            }
        })
        chat.addView(card, LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT).apply { setMargins(0, 12, 0, 14) })
    }

    private fun addAssistantBubble(text: String) = addBubble(text, false)
    private fun addUserBubble(text: String) = addBubble(text, true)
    private fun addBubble(text: String, user: Boolean) { val tv = TextView(this).apply { this.text = text; textSize = 15f; setTextColor(if (user) Color.WHITE else 0xFFE1E4E8.toInt()); setPadding(16, 14, 16, 14); background = rounded(if (user) 0xFF2B2E34.toInt() else 0xFF17191D.toInt()); gravity = Gravity.RIGHT }; chat.addView(tv, LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT).apply { setMargins(0, 6, 0, 6) }) }

    private fun showBrainSettings() { val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(18, 8, 18, 4) }; val endpoint = EditText(this).apply { hint = "عنوان Cloud Brain"; setSingleLine(); setText(brain.endpoint()); setTextColor(Color.WHITE); setHintTextColor(0xFF777C84.toInt()) }; val token = EditText(this).apply { hint = "رمز الوصول"; setSingleLine(); setText(brain.token()); setTextColor(Color.WHITE); inputType = 0x81 }; box.addView(endpoint); box.addView(token); AlertDialog.Builder(this).setTitle("ربط Cloud Brain").setView(box).setNegativeButton("إلغاء", null).setPositiveButton("حفظ") { _, _ -> brain.saveConfig(endpoint.text.toString(), token.text.toString()); refreshConnectionState() }.setNeutralButton("اختبار") { _, _ -> brain.health { ok, detail -> runOnUiThread { Toast.makeText(this, if (ok) "Cloud Brain متاح: $detail" else "فشل: $detail", Toast.LENGTH_LONG).show() } } }.show() }
    private fun connectPhone() { PermissionCoordinator.openAccessibilitySettings(this); Toast.makeText(this, "فعّل Universal Creative Agent في خدمات الوصول ثم ارجع.", Toast.LENGTH_LONG).show() }
    private fun chooseMedia() { startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply { type = "*/*"; putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true); addCategory(Intent.CATEGORY_OPENABLE) }, pickMedia) }
    private fun startSpeech() { runCatching { startActivityForResult(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply { putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM); putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ar-SA") }, speech) }.onFailure { Toast.makeText(this, "التعرف الصوتي غير متاح.", Toast.LENGTH_SHORT).show() } }
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) { super.onActivityResult(requestCode, resultCode, data); if (resultCode != RESULT_OK || data == null) return; if (requestCode == pickMedia) { data.clipData?.let { c -> for (i in 0 until c.itemCount) selectedMedia.add(c.getItemAt(i).uri.toString()) } ?: data.data?.let { selectedMedia.add(it.toString()) }; input.hint = "أضفت ${selectedMedia.size} ملف" } else if (requestCode == speech) data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()?.let { input.setText(it) } }
    private fun showDiagnostics() { AlertDialog.Builder(this).setTitle("سجل التنفيذ").setMessage(UcoaDiagnostics.recentText().takeLast(12000)).setPositiveButton("نسخ") { _, _ -> val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager; cm.setPrimaryClip(ClipData.newPlainText("UCOA", UcoaDiagnostics.recentText())) }.setNegativeButton("إغلاق", null).show() }
    private fun toggleDrawer(open: Boolean) { drawer.visibility = if (open) View.VISIBLE else View.GONE; drawerScrim.visibility = if (open) View.VISIBLE else View.GONE }
    private fun iconButton(symbol: String, description: String, click: () -> Unit): TextView = TextView(this).apply { text = symbol; textSize = 25f; setTextColor(Color.WHITE); gravity = Gravity.CENTER; contentDescription = description; background = rounded(0xFF17191D.toInt(), 50f); setOnClickListener { click() } }
    private fun rounded(color: Int, radius: Float) = android.graphics.drawable.GradientDrawable().apply { setColor(color); cornerRadius = radius }

    private class LiveExecutionCard(context: Context) : FrameLayout(context) {
        private val image = ImageView(context); private val marker = View(context); private val phase = TextView(context); private val footer = TextView(context)
        init {
            setBackgroundColor(0xFF0B0C0E.toInt()); image.scaleType = ImageView.ScaleType.FIT_CENTER; image.setBackgroundColor(0xFF111317.toInt()); addView(image, LayoutParams(-1, -1))
            marker.background = android.graphics.drawable.GradientDrawable().apply { shape = android.graphics.drawable.GradientDrawable.OVAL; setColor(0x669BE7FF); setStroke(3, 0xCCBCEFFF.toInt()) }; marker.visibility = View.GONE; addView(marker, LayoutParams(26, 26))
            phase.setTextColor(Color.WHITE); phase.textSize = 12f; phase.setPadding(12, 8, 12, 8); phase.background = roundedOverlay(); addView(phase, LayoutParams(-2, -2, Gravity.TOP or Gravity.END))
            footer.setTextColor(0xFFD8DDE5.toInt()); footer.textSize = 11f; footer.setPadding(12, 8, 12, 8); footer.background = roundedOverlay(); addView(footer, LayoutParams(-1, -2, Gravity.BOTTOM))
        }
        fun render(s: LiveExecutionState.Snapshot) {
            phase.text = "${s.phase}  •  ${s.action}"; footer.text = "${s.task.take(70)}\n${s.step}/${s.maxSteps}  •  ${if (s.verified == true) "✓ تم التحقق" else "جارٍ التنفيذ والتحقق"}"
            if (!s.screenshotBase64.isNullOrBlank()) runCatching { val bytes = Base64.decode(s.screenshotBase64, Base64.DEFAULT); image.setImageBitmap(BitmapFactory.decodeByteArray(bytes, 0, bytes.size)) }
            val x = s.tapX; val y = s.tapY
            if (x != null && y != null && s.screenWidth > 0 && s.screenHeight > 0) { marker.visibility = View.VISIBLE; post { val scale = minOf(width.toFloat() / s.screenWidth, height.toFloat() / s.screenHeight); val left = (width - s.screenWidth * scale) / 2f; val top = (height - s.screenHeight * scale) / 2f; marker.x = left + x * scale - 13; marker.y = top + y * scale - 13 } } else marker.visibility = View.GONE
        }
        private fun roundedOverlay() = android.graphics.drawable.GradientDrawable().apply { setColor(0xCC15181C.toInt()); cornerRadius = 18f }
    }
}
