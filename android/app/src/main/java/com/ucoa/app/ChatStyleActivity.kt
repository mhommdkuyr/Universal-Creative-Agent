package com.ucoa.app

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.text.InputType
import android.text.TextWatcher
import android.text.Editable
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.*
import org.json.JSONObject

/**
 * Main shell: black-first, RTL, ChatGPT-like surface. All intelligence and
 * provider credentials stay in Cloud Brain; this activity is presentation and
 * device-control orchestration only.
 */
class ChatStyleActivity : Activity() {
    private lateinit var brain: AgentBrainClient
    private lateinit var chat: LinearLayout
    private lateinit var input: EditText
    private lateinit var status: TextView
    private lateinit var drawer: LinearLayout
    private lateinit var compose: LinearLayout
    private var task: String? = null
    private var plan: TaskInterpreter.PlanResult? = null
    private var loop: UniversalAgentLoop? = null

    private val prefs by lazy { getSharedPreferences("ucoa_ui", MODE_PRIVATE) }
    private val ink = Color.rgb(245, 245, 247)
    private val muted = Color.rgb(164, 164, 171)
    private val panel = Color.rgb(30, 30, 34)
    private val panel2 = Color.rgb(20, 20, 24)
    private val selectedConversation = Color.rgb(42, 42, 48)

    private var accent: Int
        get() = Color.parseColor(prefs.getString("accent", "#6C63FF") ?: "#6C63FF")
        set(value) = prefs.edit().putString("accent", String.format("#%06X", 0xFFFFFF and value)).apply()

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        window.decorView.layoutDirection = View.LAYOUT_DIRECTION_RTL
        brain = AgentBrainClient(this)
        UcoaDiagnostics.init(this)
        setContentView(buildUi())
        brain.bootstrap()
        refresh()
        window.decorView.postDelayed({ firstPermissionPrompt() }, 600)
    }

    override fun onResume() {
        super.onResume()
        if (::status.isInitialized) refresh()
    }

    private fun buildUi(): View {
        val root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK) }
        val main = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(12, 14, 12, 8)
        }

        val top = LinearLayout(this).apply {
            gravity = Gravity.CENTER_VERTICAL
            layoutDirection = View.LAYOUT_DIRECTION_RTL
        }
        top.addView(uiButton("☰", 48) { drawer.visibility = View.VISIBLE })
        top.addView(
            TextView(this).apply {
                text = "✦  الذكاء العملي الكامل"
                textSize = 15f
                gravity = Gravity.CENTER
                setTextColor(accent)
                setBackgroundColor(Color.rgb(36, 36, 42))
            },
            LinearLayout.LayoutParams(0, 48, 1f).apply { setMargins(10, 0, 10, 0) }
        )
        top.addView(uiButton("⋯", 48) { conversationSettings() })
        main.addView(top)

        status = textView("جاري فحص Cloud Brain…", 12f, muted, Gravity.CENTER)
        main.addView(status, LinearLayout.LayoutParams(-1, 32))

        val scroll = ScrollView(this).apply {
            layoutParams = LinearLayout.LayoutParams(-1, 0, 1f)
            isFillViewport = true
        }
        chat = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(8, 24, 8, 24)
        }
        scroll.addView(chat)
        main.addView(scroll)

        chat.addView(textView("كيف يمكنني مساعدتك؟", 28f, ink, Gravity.CENTER), fixed(70))
        chat.addView(
            textView("اكتب أي مهمة. سأفهمها، أبني خطة، أعرض المخاطر والأذونات، ثم أنتظر موافقتك قبل التنفيذ.", 15f, muted, Gravity.CENTER).apply {
                setPadding(8, 0, 8, 0)
            },
            fixed(86)
        )

        addQuickAction("إنشاء صورة أو ملصق", "أنشئ لي صورة أو ملصقًا…")
        addQuickAction("الكتابة أو التحرير", "اكتب أو حرر النص التالي…")
        addQuickAction("ابحث في الويب", "ابحث في الويب عن…")
        addQuickAction("نفّذ مهمة على تطبيق", "نفّذ المهمة التالية داخل التطبيق…")

        compose = LinearLayout(this).apply {
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 4, 0, 4)
        }
        compose.addView(uiButton("◦◦", 44) { speech() })
        input = EditText(this).apply {
            hint = "اسأل الذكاء العملي الكامل"
            textSize = 17f
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
            setTextColor(ink)
            setHintTextColor(muted)
            setBackgroundColor(panel)
            setPadding(16, 10, 16, 10)
            minLines = 1
            maxLines = 5
            gravity = Gravity.CENTER_VERTICAL
            addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) { resizeComposer() }
                override fun afterTextChanged(s: Editable?) = Unit
            })
        }
        compose.addView(input, LinearLayout.LayoutParams(0, 56, 1f).apply { setMargins(6, 0, 6, 0) })
        compose.addView(uiButton("+", 44) { media() })
        compose.addView(uiButton("↑", 44) { submit() })
        main.addView(compose)

        root.addView(main)
        drawer = buildDrawer()
        drawer.visibility = View.GONE
        root.addView(drawer, FrameLayout.LayoutParams(340, -1, Gravity.START))
        return root
    }

    private fun resizeComposer() {
        if (!::input.isInitialized) return
        val len = input.text?.length ?: 0
        val targetLines = when {
            len > 220 -> 5
            len > 130 -> 4
            len > 70 -> 3
            len > 25 -> 2
            else -> 1
        }
        input.maxLines = targetLines.coerceAtLeast(1)
        val lp = input.layoutParams
        lp.height = (56 + (targetLines - 1) * 18).coerceAtMost(108).dp()
        input.layoutParams = lp
    }

    private fun addQuickAction(title: String, seed: String) {
        val item = textView("$title   ›", 16f, ink, Gravity.RIGHT).apply {
            setPadding(14, 0, 14, 0)
            setBackgroundColor(panel2)
            setOnClickListener { input.setText(seed); input.setSelection(input.length()); input.requestFocus() }
        }
        chat.addView(item, LinearLayout.LayoutParams(-1, 54).apply { setMargins(0, 0, 0, 6) })
    }

    private fun buildDrawer(): LinearLayout {
        val d = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(18, 24, 18, 18)
            setBackgroundColor(Color.rgb(17, 17, 22))
            layoutDirection = View.LAYOUT_DIRECTION_RTL
        }
        val header = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        header.addView(textView("المحادثات", 24f, ink, Gravity.RIGHT), LinearLayout.LayoutParams(0, 54, 1f))
        header.addView(uiButton("×", 44) { drawer.visibility = View.GONE })
        d.addView(header)

        val search = EditText(this).apply {
            hint = "بحث في المحادثات"
            setHintTextColor(muted)
            setTextColor(ink)
            setBackgroundColor(panel)
            setPadding(14, 0, 14, 0)
        }
        d.addView(search, LinearLayout.LayoutParams(-1, 50).apply { setMargins(0, 8, 0, 12) })

        listOf(
            "مهمة جديدة",
            "بحث عن حلقة سولفليكس",
            "تحرير فيديو في CapCut",
            "إنشاء صورة للمنتج",
            "مقارنة أسعار"
        ).forEach { value ->
            val row = textView(value, 15f, ink, Gravity.RIGHT).apply {
                setPadding(14, 0, 14, 0)
                setBackgroundColor(if (value == "مهمة جديدة") selectedConversation else panel2)
                setOnClickListener {
                    task = null
                    plan = null
                    chat.removeViews(5, (chat.childCount - 5).coerceAtLeast(0))
                    drawer.visibility = View.GONE
                }
            }
            d.addView(row, LinearLayout.LayoutParams(-1, 50).apply { setMargins(0, 0, 0, 6) })
        }

        d.addView(Space(this), LinearLayout.LayoutParams(1, 8))
        d.addView(drawerRow("▦  مكتبة التطبيقات المرتبطة") { apps() })
        d.addView(drawerRow("⚙  الإعدادات") { settings() })
        d.addView(drawerRow("☁  حالة Cloud Brain") { cloudStatus() })
        d.addView(drawerRow("◉  التشخيص والتتبع") { diagnostics() })
        d.addView(Space(this), LinearLayout.LayoutParams(1, 0, 1f))
        d.addView(textView("الواجهة خفيفة • الذكاء والتحديثات في السحابة", 12f, muted, Gravity.CENTER))
        return d
    }

    private fun drawerRow(title: String, action: () -> Unit): TextView = textView(title, 15f, ink, Gravity.RIGHT).apply {
        setPadding(14, 0, 14, 0)
        setBackgroundColor(panel)
        setOnClickListener { action() }
        layoutParams = LinearLayout.LayoutParams(-1, 50).apply { setMargins(0, 0, 0, 6) }
    }

    private fun refresh() {
        brain.readiness { transport, ready, detail ->
            runOnUiThread {
                status.text = when {
                    !PermissionCoordinator.isAccessibilityEnabled(this) -> "○ يحتاج إذن التحكم"
                    !PermissionCoordinator.isServiceLive() -> "○ إذن الوصول مفعّل — شغّل الخدمة"
                    transport && ready -> "● Cloud Brain متصل • التنفيذ متاح"
                    else -> "○ $detail"
                }
                status.setTextColor(if (transport && ready) Color.rgb(74, 222, 128) else muted)
            }
        }
    }

    private fun firstPermissionPrompt() {
        if (PermissionCoordinator.isAccessibilityEnabled(this)) return
        AlertDialog.Builder(this)
            .setTitle("إذن التحكم مطلوب")
            .setMessage("لن ينفذ التطبيق أي خطوة قبل موافقتك. لتفعيل التحكم افتح خدمة إمكانية الوصول.")
            .setNegativeButton("لاحقًا", null)
            .setPositiveButton("فتح الأذونات") { _, _ -> PermissionCoordinator.openAccessibilitySettings(this) }
            .show()
    }

    private fun submit() {
        val q = input.text.toString().trim()
        if (q.isEmpty()) return
        task = q
        input.setText("")
        bubble("أنت\n$q", true)
        bubble("الوكيل\nأفهم الطلب وأبني خطة قابلة للمراجعة…", false)
        UcoaDiagnostics.log("UI_TASK", "طلب جديد", "chars=${q.length}")
        val local = TaskInterpreter().analyze(q, emptyList())
        brain.plan(q, emptyList()) { response ->
            runOnUiThread {
                val planned = if (response.ok && response.body != null) {
                    val array = response.body.optJSONArray("steps")
                    val steps = mutableListOf<String>()
                    if (array != null) for (i in 0 until array.length()) steps += array.optString(i)
                    if (steps.isNotEmpty()) local.copy(summary = response.body.optString("summary", local.summary), steps = steps) else local
                } else local
                plan = planned
                bubble(
                    "الوكيل\n${if (response.ok) "الخطة السحابية جاهزة. لن يبدأ التنفيذ قبل موافقتك." else "تعذر التخطيط السحابي مؤقتًا؛ أعرض خطة محلية للمراجعة."}",
                    false
                )
                showPlan(planned)
            }
        }
    }

    private fun showPlan(p: TaskInterpreter.PlanResult) {
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(18, 18, 18, 18)
            setBackgroundColor(panel2)
        }
        box.addView(textView("خطة التنفيذ", 20f, accent, Gravity.RIGHT))
        box.addView(textView(p.summary, 14f, muted, Gravity.RIGHT))
        box.addView(textView(p.steps.mapIndexed { i, s -> "${i + 1}. $s" }.joinToString("\n"), 15f, ink, Gravity.RIGHT).apply { setPadding(0, 14, 0, 14) })
        box.addView(textView("الأذونات والموافقات", 17f, accent, Gravity.RIGHT))
        val access = PermissionCoordinator.isAccessibilityEnabled(this)
        box.addView(textView(if (access) "✓ خدمة الوصول مفعلة" else "! يحتاج صلاحية الوصول والتحكم", 14f, if (access) Color.rgb(74, 222, 128) else Color.rgb(251, 191, 36), Gravity.RIGHT))

        val approve = Button(this).apply {
            text = "موافقة وتنفيذ"
            setTextColor(Color.WHITE)
            setBackgroundColor(accent)
            setOnClickListener { approveExecute() }
        }
        val review = Button(this).apply { text = "مراجعة الخطة"; setOnClickListener { editPlan() } }
        box.addView(approve, LinearLayout.LayoutParams(-1, 50).apply { setMargins(0, 10, 0, 6) })
        box.addView(review, LinearLayout.LayoutParams(-1, 50).apply { setMargins(0, 0, 0, 6) })
        if (!access) box.addView(Button(this).apply { text = "فتح الأذونات"; setOnClickListener { PermissionCoordinator.openAccessibilitySettings(this@ChatStyleActivity) } })
        chat.addView(box, LinearLayout.LayoutParams(-1, -2).apply { setMargins(0, 10, 0, 12) })
    }

    private fun editPlan() {
        val current = plan ?: return
        val editor = EditText(this).apply {
            setText(current.steps.mapIndexed { i, s -> "${i + 1}. $s" }.joinToString("\n"))
            setTextColor(ink)
            setHintTextColor(muted)
            minLines = 7
            setBackgroundColor(panel)
        }
        AlertDialog.Builder(this)
            .setTitle("مراجعة الخطة")
            .setMessage("التعديل لا يبدأ التنفيذ.")
            .setView(editor)
            .setNegativeButton("إلغاء", null)
            .setPositiveButton("حفظ") { _, _ ->
                val steps = editor.text.toString().lines().map { it.trim() }.filter { it.isNotEmpty() }.map { it.replaceFirst(Regex("^\\d+\\.\\s*"), "") }
                if (steps.isNotEmpty()) {
                    plan = current.copy(steps = steps)
                    showPlan(plan!!)
                }
            }.show()
    }

    private fun approveExecute() {
        val q = task ?: return
        val p = plan ?: return
        if (!PermissionCoordinator.isAccessibilityEnabled(this) || !PermissionCoordinator.isServiceLive()) {
            bubble("الوكيل\nلم أبدأ التنفيذ: فعّل إذن الوصول وشغّل الخدمة أولًا.", false)
            PermissionCoordinator.openAccessibilitySettings(this)
            return
        }
        bubble("الوكيل\n✓ تمت الموافقة. أبدأ التنفيذ مع التحقق بعد كل خطوة.", false)
        brain.telemetry("execution_approved", JSONObject().put("steps", p.steps.size))
        val approved = q + "\nالخطة المعتمدة:\n" + p.steps.mapIndexed { i, s -> "${i + 1}. $s" }.joinToString("\n")
        loop = UniversalAgentLoop(brain)
        loop!!.start(approved, object : UniversalAgentLoop.Listener {
            override fun onEvent(eventText: String) {
                runOnUiThread { status.text = eventText.take(180); bubble("الوكيل\n$eventText", false) }
            }
            override fun onHumanIntervention(request: HumanIntervention.Request) {
                runOnUiThread { confirm(request.title, request.message, request.actionLabel) { loop?.resume() } }
            }
            override fun onConfirmationRequired(reason: String) {
                runOnUiThread { confirm("تأكيد مطلوب", reason, "متابعة") { loop?.resume() } }
            }
            override fun onFinished(success: Boolean) {
                runOnUiThread {
                    val message = if (success) "✓ اكتملت المهمة وتم التحقق." else "توقفت المهمة قبل إثبات الاكتمال."
                    bubble("الوكيل\n$message", false)
                    brain.reportOutcome(if (success) "success" else "stopped", JSONObject().put("ui_verified", success))
                }
            }
        })
    }

    private fun confirm(title: String, message: String, yes: String, go: () -> Unit) {
        AlertDialog.Builder(this)
            .setTitle(title)
            .setMessage(message)
            .setNegativeButton("إلغاء") { _, _ -> loop?.stop() }
            .setPositiveButton(yes) { _, _ -> go() }
            .setCancelable(false)
            .show()
    }

    private fun bubble(message: String, user: Boolean) {
        val b = textView(message, 15f, ink, Gravity.RIGHT).apply {
            setPadding(18, 14, 18, 14)
            setBackgroundColor(if (user) accent.withAlpha(70) else panel2)
        }
        chat.addView(b, LinearLayout.LayoutParams(-1, -2).apply { setMargins(0, 0, 0, 8) })
    }

    private fun conversationSettings() {
        AlertDialog.Builder(this)
            .setTitle("إعدادات المحادثة")
            .setItems(arrayOf("إعادة تسمية", "النماذج والمحركات", "الموافقة مطلوبة قبل التنفيذ", "الرؤية وتحليل الشاشة", "سجل التنفيذ والتشخيص")) { _, which ->
                if (which == 1) cloudStatus()
                if (which == 4) diagnostics()
            }.show()
    }

    private fun settings() {
        val items = arrayOf("المظهر واللون الثانوي", "الحساب", "النماذج والمحركات", "التطبيقات والصلاحيات", "التتبع والتشخيص", "عنوان Cloud Brain", "إعادة تهيئة جلسة السحابة")
        AlertDialog.Builder(this)
            .setTitle("الإعدادات")
            .setItems(items) { _, which ->
                when (which) {
                    0 -> appearanceSettings()
                    2 -> cloudStatus()
                    3 -> apps()
                    4 -> diagnostics()
                    5 -> endpointSettings()
                    6 -> { brain.resetSession(); brain.bootstrap(); toast("تمت تهيئة جلسة سحابية جديدة") }
                }
            }.show()
    }

    private fun appearanceSettings() {
        val labels = arrayOf("بنفسجي", "أزرق", "أخضر", "برتقالي", "وردي", "رمادي")
        val values = intArrayOf(
            Color.rgb(108, 99, 255), Color.rgb(59, 130, 246), Color.rgb(16, 185, 129),
            Color.rgb(245, 158, 11), Color.rgb(236, 72, 153), Color.rgb(148, 163, 184)
        )
        AlertDialog.Builder(this).setTitle("اللون الثانوي").setItems(labels) { _, which ->
            accent = values[which]
            recreate()
        }.show()
    }

    private fun endpointSettings() {
        val editor = EditText(this).apply {
            hint = "https://…"
            setText(brain.endpoint())
            setTextColor(ink)
            setHintTextColor(muted)
        }
        AlertDialog.Builder(this).setTitle("عنوان Cloud Brain").setMessage("لا تضع مفتاح مزود AI هنا. مفاتيح النماذج تبقى في السحابة.")
            .setView(editor)
            .setNegativeButton("إلغاء", null)
            .setPositiveButton("حفظ") { _, _ -> brain.saveConfig(editor.text.toString(), brain.token()); brain.bootstrap(); refresh() }
            .show()
    }

    private fun cloudStatus() {
        brain.readiness { transport, ready, detail ->
            runOnUiThread {
                AlertDialog.Builder(this)
                    .setTitle("حالة Cloud Brain")
                    .setMessage("النقل: ${if (transport) "متصل" else "غير متصل"}\nالعقل: ${if (ready) "جاهز" else "غير جاهز"}\n$detail\n\nالمفاتيح السرية لا توجد في APK؛ الجلسة قصيرة العمر ومُنشأة عند التشغيل.")
                    .setPositiveButton("تحديث") { _, _ -> brain.bootstrap(); refresh() }
                    .setNegativeButton("إغلاق", null).show()
            }
        }
    }

    private fun apps() {
        val installed = AppDiscovery.installedLabels(this).take(80)
        AlertDialog.Builder(this).setTitle("مكتبة التطبيقات المرتبطة")
            .setMessage(if (installed.isEmpty()) "لا توجد تطبيقات مكتشفة." else installed.joinToString("\n"))
            .setPositiveButton("إغلاق", null).show()
    }

    private fun diagnostics() {
        val log = UcoaDiagnostics.recentText()
        AlertDialog.Builder(this).setTitle("التشخيص والتتبع")
            .setMessage(log.takeLast(14000))
            .setPositiveButton("إغلاق", null)
            .setNeutralButton("نسخ السجل") { _, _ ->
                val cm = getSystemService(CLIPBOARD_SERVICE) as ClipboardManager
                cm.setPrimaryClip(ClipData.newPlainText("UCOA diagnostics", log))
            }.show()
    }

    private fun media() {
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            type = "*/*"
            addCategory(Intent.CATEGORY_OPENABLE)
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
        }, 401)
    }

    private fun speech() {
        try {
            startActivityForResult(Intent("android.speech.action.RECOGNIZE_SPEECH").apply {
                putExtra("android.speech.extra.LANGUAGE_MODEL", "free_form")
                putExtra("android.speech.extra.LANGUAGE", "ar-SA")
            }, 402)
        } catch (_: Exception) { toast("خدمة الإملاء الصوتي غير متاحة") }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode == RESULT_OK && requestCode == 402) {
            data?.getStringArrayListExtra("android.speech.extra.RESULTS")?.firstOrNull()?.let {
                input.setText(it)
                input.setSelection(input.length())
            }
        }
    }

    private fun uiButton(value: String, size: Int, action: () -> Unit): TextView = textView(value, 23f, ink, Gravity.CENTER).apply {
        setBackgroundColor(panel)
        setOnClickListener { action() }
        layoutParams = LinearLayout.LayoutParams(size, 52)
    }

    private fun textView(value: String, size: Float, color: Int, gravity: Int): TextView = TextView(this).apply {
        text = value
        textSize = size
        setTextColor(color)
        this.gravity = gravity
    }

    private fun fixed(h: Int) = LinearLayout.LayoutParams(-1, h)

    private fun Int.dp(): Int = (this * resources.displayMetrics.density).toInt()

    private fun Int.withAlpha(alpha: Int): Int = Color.argb(alpha.coerceIn(0, 255), Color.red(this), Color.green(this), Color.blue(this))

    private fun toast(message: String) = Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
}
