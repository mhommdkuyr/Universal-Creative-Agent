package com.ucoa.app

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.speech.RecognizerIntent
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.*

class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var chat: LinearLayout
    private lateinit var input: EditText
    private lateinit var attachButton: ImageButton
    private lateinit var micButton: ImageButton
    private lateinit var sendButton: ImageButton
    private lateinit var connectButton: Button
    private val selectedMedia = mutableListOf<String>()
    private val interpreter = TaskInterpreter()
    private var latestPlan: TaskInterpreter.PlanResult? = null
    private var pendingReview: EditText? = null

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
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
        }
        val top = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(28, 34, 28, 16)
        }
        val title = TextView(this).apply {
            text = "Universal Creative Agent"
            textSize = 21f
            setTextColor(Color.BLACK)
            gravity = Gravity.CENTER_HORIZONTAL
        }
        status = TextView(this).apply {
            textSize = 13f
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(0, 8, 0, 12)
        }
        connectButton = Button(this).apply {
            text = "ربط الهاتف بنقرة واحدة"
            setOnClickListener { connectPhone() }
        }
        top.addView(title)
        top.addView(status)
        top.addView(connectButton)
        root.addView(top)

        val scroll = ScrollView(this).apply {
            fillViewport = true
            layoutParams = LinearLayout.LayoutParams(-1, 0, 1f)
        }
        chat = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 18, 24, 24)
        }
        addAssistantBubble("أنا جاهز. اكتب أي مهمة تريد تنفيذها، وأرفق فيديو أو صورة أو ملف عند الحاجة. سأفهمها وأعرض لك خطة قبل التنفيذ.")
        scroll.addView(chat)
        root.addView(scroll)

        val composer = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(14, 10, 14, 14)
        }
        attachButton = ImageButton(this).apply {
            setImageResource(android.R.drawable.ic_menu_add)
            contentDescription = "رفع الوسائط"
            setBackgroundColor(Color.TRANSPARENT)
            setOnClickListener { chooseMedia() }
        }
        micButton = ImageButton(this).apply {
            setImageResource(android.R.drawable.ic_btn_speak_now)
            contentDescription = "الصوت"
            setBackgroundColor(Color.TRANSPARENT)
            setOnClickListener { startSpeech() }
        }
        input = EditText(this).apply {
            hint = "اكتب ما تريد تنفيذه…"
            minLines = 1
            maxLines = 5
            setPadding(16, 12, 16, 12)
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        sendButton = ImageButton(this).apply {
            setImageResource(android.R.drawable.ic_media_play)
            contentDescription = "إرسال"
            setBackgroundColor(Color.TRANSPARENT)
            setOnClickListener { analyzeTask() }
        }
        composer.addView(attachButton, LinearLayout.LayoutParams(48, 56))
        composer.addView(micButton, LinearLayout.LayoutParams(48, 56))
        composer.addView(input)
        composer.addView(sendButton, LinearLayout.LayoutParams(56, 56))
        root.addView(composer)
        return root
    }

    private fun refreshConnectionState() {
        val enabled = PermissionCoordinator.isAccessibilityEnabled(this)
        val live = PermissionCoordinator.isServiceLive()
        status.text = when {
            live -> "● متصل ويستطيع التفاعل مع الهاتف"
            enabled -> "● الصلاحية مفعلة — جارٍ تهيئة الخدمة"
            else -> "○ غير متصل — فعّل الوصول مرة واحدة من إعدادات Android"
        }
        connectButton.text = when {
            live -> "الهاتف متصل"
            enabled -> "إعادة تهيئة الاتصال"
            else -> "ربط الهاتف بنقرة واحدة"
        }
        connectButton.isEnabled = !live
    }

    private fun connectPhone() {
        PermissionCoordinator.openAccessibilitySettings(this)
        Toast.makeText(this, "فعّل Universal Creative Agent ثم ارجع للتطبيق؛ سيكتشف الاتصال تلقائيًا.", Toast.LENGTH_LONG).show()
    }

    private fun chooseMedia() {
        val i = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            type = "*/*"
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
            addCategory(Intent.CATEGORY_OPENABLE)
        }
        startActivityForResult(i, pickMedia)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == pickMedia && resultCode == RESULT_OK && data != null) {
            data.clipData?.let { clip ->
                for (i in 0 until clip.itemCount) selectedMedia.add(clip.getItemAt(i).uri.toString())
            } ?: data.data?.let { selectedMedia.add(it.toString()) }
            input.setHint("أضفت ${selectedMedia.size} ملف — اكتب المطلوب")
        }
        if (requestCode == speech && resultCode == RESULT_OK && data != null) {
            val values = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
            if (!values.isNullOrEmpty()) input.setText(values[0])
        }
    }

    private fun startSpeech() {
        try {
            val i = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ar-SA")
                putExtra(RecognizerIntent.EXTRA_PROMPT, "تحدث بطلبك")
            }
            startActivityForResult(i, speech)
        } catch (_: Exception) {
            Toast.makeText(this, "التعرف الصوتي غير متاح على هذا الجهاز.", Toast.LENGTH_SHORT).show()
        }
    }

    private fun analyzeTask() {
        val text = input.text.toString().trim()
        if (text.isEmpty()) return
        addUserBubble(text + if (selectedMedia.isNotEmpty()) "\n📎 ${selectedMedia.size} ملف" else "")
        latestPlan = interpreter.analyze(text, selectedMedia)
        addPlanCard(latestPlan!!)
        input.setText("")
    }

    private fun addAssistantBubble(text: String) {
        val tv = TextView(this).apply {
            this.text = text
            textSize = 16f
            setTextColor(Color.DKGRAY)
            setPadding(18, 18, 18, 18)
            setBackgroundColor(0xFFF2F2F2.toInt())
        }
        chat.addView(tv, LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT).apply { setMargins(0, 0, 0, 18) })
    }

    private fun addUserBubble(text: String) {
        val tv = TextView(this).apply {
            this.text = text
            textSize = 16f
            setTextColor(Color.WHITE)
            setPadding(18, 18, 18, 18)
            setBackgroundColor(0xFF222222.toInt())
        }
        chat.addView(tv, LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT).apply { setMargins(0, 0, 0, 18) })
    }

    private fun addPlanCard(plan: TaskInterpreter.PlanResult) {
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(22, 20, 22, 20)
            setBackgroundColor(0xFFF7F7F7.toInt())
        }
        val heading = TextView(this).apply {
            text = "خطة التنفيذ"
            textSize = 18f
            setTextColor(Color.BLACK)
        }
        val summary = TextView(this).apply {
            text = plan.summary
            textSize = 14f
            setPadding(0, 10, 0, 8)
        }
        val steps = TextView(this).apply {
            text = plan.steps.mapIndexed { i, s -> "${i + 1}. $s" }.joinToString("\n")
            textSize = 15f
            setPadding(0, 8, 0, 18)
        }
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val review = Button(this).apply {
            text = "مراجعة وتعديل"
            setOnClickListener { showReview(plan) }
        }
        val execute = Button(this).apply {
            text = "تنفيذ الآن"
            setOnClickListener { executePlan(plan, card) }
        }
        row.addView(execute, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(review, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        card.addView(heading)
        card.addView(summary)
        card.addView(steps)
        card.addView(row)
        chat.addView(card, LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT).apply { setMargins(0, 0, 0, 18) })
    }

    private fun showReview(plan: TaskInterpreter.PlanResult) {
        val editor = EditText(this).apply {
            setText(plan.steps.mapIndexed { i, s -> "${i + 1}. $s" }.joinToString("\n"))
            minLines = 8
        }
        pendingReview = editor
        AlertDialog.Builder(this)
            .setTitle("تعديل خطة التنفيذ")
            .setView(editor)
            .setNegativeButton("إلغاء", null)
            .setPositiveButton("حفظ الخطة") { _, _ ->
                addAssistantBubble("تم حفظ التعديلات. اضغط تنفيذ بعد مراجعة الخطة الجديدة.")
            }.show()
    }

    private fun executePlan(plan: TaskInterpreter.PlanResult, card: View) {
        if (!PermissionCoordinator.isServiceLive()) {
            Toast.makeText(this, "فعّل ربط الهاتف أولًا.", Toast.LENGTH_LONG).show()
            connectPhone()
            return
        }
        val first = when (plan.taskType) {
            "browser" -> "افتح Chrome"
            else -> "الرئيسية"
        }
        val action = org.json.JSONArray().put(org.json.JSONObject().apply {
            put("action", if (first.startsWith("افتح")) "open_app" else "home")
            if (first.startsWith("افتح")) put("package", "com.android.chrome")
            put("delay_ms", 250)
        })
        card.isEnabled = false
        ActionPlanRunner().run(action.toString()) { event ->
            runOnUiThread { status.append("\n$event") }
        }
        addAssistantBubble("بدأت التنفيذ. سأراقب الخطوات وأظهر حالة كل إجراء.")
    }
}
