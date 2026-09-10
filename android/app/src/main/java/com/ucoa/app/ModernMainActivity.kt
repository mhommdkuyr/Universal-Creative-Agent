package com.ucoa.app

import android.app.Activity
import android.app.AlertDialog
import android.graphics.BitmapFactory
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.widget.*
import android.graphics.Color
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject

class ModernMainActivity : Activity() {
    private lateinit var chat: LinearLayout
    private lateinit var status: TextView
    private lateinit var input: EditText
    private lateinit var brain: AgentBrainClient
    private var loop: UniversalAgentLoop? = null
    private var waitingRequest: HumanIntervention.Request? = null
    private var pendingTask: String? = null
    private var pendingPlan: TaskInterpreter.PlanResult? = null
    private var pendingPlanCard: View? = null
    private val bg = Color.rgb(14,16,23)
    private val card = Color.rgb(23,26,36)
    private val card2 = Color.rgb(31,34,47)
    private val white = Color.rgb(245,246,250)
    private val muted = Color.rgb(158,163,178)
    private val purple = Color.rgb(124,92,255)

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        window.decorView.layoutDirection = View.LAYOUT_DIRECTION_RTL
        brain = AgentBrainClient(this)
        setContentView(build())
        refreshStatus()
        window.decorView.postDelayed({ showPermissionGateIfNeeded() }, 350L)
    }

    override fun onResume() {
        super.onResume()
        if (::status.isInitialized) refreshStatus()
    }

    private fun build(): View {
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(bg); setPadding(18,18,18,10) }
        val head = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL }
        head.addView(tv("الذكاء العملي الكامل",24f,white,true))
        status = tv("جاري فحص الاتصال…",12f,muted,false); head.addView(status); root.addView(head)
        val scroll = ScrollView(this).apply { layoutParams = LinearLayout.LayoutParams(-1,0,1f) }
        chat = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(0,18,0,18) }
        scroll.addView(chat); root.addView(scroll)
        addCard("مهمة جديدة", "اكتب طلبك. سأفهمه، أبني خطة واضحة، أعرض الأذونات والموافقات، ثم أنتظر موافقتك قبل أي تنفيذ.")
        val composer = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        val attach = Button(this).apply { text="＋"; setOnClickListener{toast("أضف الوسائط من زر المرفقات في النسخة الموسعة")}}
        input = EditText(this).apply { hint="اكتب ما تريد تنفيذه…"; setTextColor(white); setHintTextColor(muted); setBackgroundColor(card2); setPadding(14,10,14,10); layoutParams=LinearLayout.LayoutParams(0,56,1f) }
        val send = Button(this).apply { text="إرسال"; setOnClickListener{startTask()} }
        composer.addView(attach,LinearLayout.LayoutParams(52,56)); composer.addView(input); composer.addView(send,LinearLayout.LayoutParams(76,56)); root.addView(composer)
        return root
    }

    private fun refreshStatus() {
        brain.readiness { transport, ready, detail -> runOnUiThread {
            val access = PermissionCoordinator.isAccessibilityEnabled(this)
            val live = PermissionCoordinator.isServiceLive()
            status.text = when {
                !access -> "○ يحتاج إذن التحكم بالهاتف — اضغط ربط الأذونات"
                access && !live -> "○ إذن الوصول مفعّل لكن خدمة التحكم لم تبدأ بعد"
                transport && ready && live -> "● العقل السحابي وخدمة التحكم جاهزان"
                transport && ready -> "● العقل السحابي جاهز — بانتظار خدمة التحكم"
                else -> "○ ${detail.take(120)}"
            }
        }}
    }

    private fun showPermissionGateIfNeeded() {
        if (PermissionCoordinator.isAccessibilityEnabled(this)) return
        val box = LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(22,8,22,8) }
        box.addView(tv("صلاحية التحكم مطلوبة",20f,white,true))
        box.addView(tv("حتى ينفذ الوكيل المهام على الهاتف، يحتاج إلى خدمة الوصول Accessibility. لن يبدأ أي إجراء قبل عرض الخطة والحصول على موافقتك.",14f,muted,false))
        val open = Button(this).apply { text="فتح إعدادات الوصول"; setOnClickListener { PermissionCoordinator.openAccessibilitySettings(this@ModernMainActivity) } }
        box.addView(open)
        AlertDialog.Builder(this).setTitle("إعداد الهاتف أول مرة").setView(box).setPositiveButton("سأفعلها الآن", null).setCancelable(false).show()
    }

    private fun startTask() {
        val task = input.text.toString().trim(); if (task.isEmpty()) return
        pendingTask = task; input.setText(""); addUser(task)
        val fallback = TaskInterpreter().analyze(task, emptyList())
        addAssistant("أفهم المهمة وأبني خطة قابلة للمراجعة…")
        brain.plan(task, emptyList()) { r -> runOnUiThread {
            val planned = if (r.ok && r.body != null) {
                val p = r.body; val arr = p.optJSONArray("steps")
                val steps = mutableListOf<String>()
                if (arr != null) for (i in 0 until arr.length()) steps += arr.optString(i)
                if (steps.isNotEmpty()) fallback.copy(summary=p.optString("summary",fallback.summary),steps=steps)
                else fallback
            } else fallback
            pendingPlan = planned
            addAssistant(if (r.ok) "الخطة وصلت. لن أبدأ التنفيذ حتى تضغط موافقة وتنفيذ أو تراجع الخطة." else "تعذر الوصول للمخطط السحابي الآن؛ أعرض الخطة المحلية للمراجعة، ولن أنفذ تلقائيًا.")
            showPlan(planned)
        }}
    }

    private fun showPlan(plan: TaskInterpreter.PlanResult) {
        pendingPlanCard?.let { chat.removeView(it) }
        val box = LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(18,16,18,16); setBackgroundColor(card) }
        box.addView(tv("خطة التنفيذ — بانتظار موافقتك",19f,white,true))
        box.addView(tv(plan.summary,14f,muted,false))
        val stepsText = plan.steps.mapIndexed { i,s -> "${i+1}. $s" }.joinToString("\n")
        box.addView(tv(stepsText,15f,white,false))
        box.addView(tv("الأذونات: خدمة الوصول مطلوبة للتحكم الفعلي. لن تُنفّذ الخطوة الأولى قبل الموافقة.",13f,muted,false))
        val row = LinearLayout(this).apply { orientation=LinearLayout.HORIZONTAL }
        val approve = Button(this).apply { text="موافقة وتنفيذ"; setOnClickListener { approveAndExecute() } }
        val review = Button(this).apply { text="مراجعة وتعديل"; setOnClickListener { showPlanEditor(plan) } }
        row.addView(approve,LinearLayout.LayoutParams(0,56,1f)); row.addView(review,LinearLayout.LayoutParams(0,56,1f)); box.addView(row)
        if (!PermissionCoordinator.isAccessibilityEnabled(this)) {
            box.addView(Button(this).apply { text="منح إذن التحكم"; setOnClickListener { PermissionCoordinator.openAccessibilitySettings(this@ModernMainActivity) } })
        }
        chat.addView(box,LinearLayout.LayoutParams(-1,-2).apply{setMargins(0,0,0,12)}); pendingPlanCard=box
    }

    private fun showPlanEditor(plan: TaskInterpreter.PlanResult) {
        val editor = EditText(this).apply { setText(plan.steps.mapIndexed{i,s->"${i+1}. $s"}.joinToString("\n")); minLines=7; setTextColor(white); setHintTextColor(muted) }
        AlertDialog.Builder(this).setTitle("مراجعة الخطة قبل التنفيذ").setMessage("عدّل الخطوات كما تريد ثم احفظها. لن يبدأ التنفيذ عند الحفظ.").setView(editor).setNegativeButton("إلغاء",null).setPositiveButton("حفظ الخطة") { _,_ ->
            val steps=editor.text.toString().lines().map{it.trim()}.filter{it.isNotEmpty()}.map{it.replaceFirst(Regex("^\\d+\\.\\s*"),"")}
            if (steps.isNotEmpty()) { pendingPlan=plan.copy(steps=steps); addAssistant("تم حفظ التعديل. الخطة ما زالت بانتظار موافقتك."); showPlan(pendingPlan!!) }
        }.show()
    }

    private fun approveAndExecute() {
        val task=pendingTask ?: return
        val plan=pendingPlan ?: return
        if (!PermissionCoordinator.isAccessibilityEnabled(this) || !PermissionCoordinator.isServiceLive()) {
            addAssistant("لا يمكن البدء بعد: يجب تفعيل خدمة الوصول وتشغيلها أولًا. افتح الإعدادات ثم ارجع واضغط موافقة وتنفيذ مرة أخرى.")
            PermissionCoordinator.openAccessibilitySettings(this)
            return
        }
        addAssistant("✅ تمت الموافقة على الخطة. أبدأ التنفيذ الآن فقط.")
        executeApprovedPlan(task,plan)
    }

    private fun executeApprovedPlan(task:String,plan:TaskInterpreter.PlanResult) {
        pendingPlanCard?.isEnabled=false
        loop=UniversalAgentLoop(brain)
        val approvedTask = task + "\nالخطة المعتمدة من المستخدم:\n" + plan.steps.mapIndexed{i,s->"${i+1}. $s"}.joinToString("\n")
        loop!!.start(approvedTask,object:UniversalAgentLoop.Listener {
            override fun onEvent(text:String){runOnUiThread{status.text=text.take(160);addAssistant(text.take(700))}}
            override fun onHumanIntervention(request:HumanIntervention.Request){runOnUiThread{waitingRequest=request;showHuman(request)}}
            override fun onConfirmationRequired(reasons:String){runOnUiThread{showDecision("تأكيد أمني مطلوب",reasons,listOf("تمت المراجعة","إلغاء"))}}
            override fun onFinished(success:Boolean){runOnUiThread{pendingPlanCard?.isEnabled=true;if(success)showResult() else if(waitingRequest==null)addAssistant("توقفت المهمة ولم أعلن النجاح قبل إثباته.")}}
        })
    }

    private fun showHuman(r:HumanIntervention.Request){
        val actions=when(r.kind){"signup"->listOf("نفذ التسجيل بنفسي","تم التسجيل — متابعة","إلغاء");"verification"->listOf("أدخل الرمز بنفسي","تم التحقق — متابعة","إلغاء");"subscription","credits"->listOf("متابعة الاشتراك","استخدام خدمة بديلة","رفض");else->listOf(r.actionLabel,"إلغاء")}
        showDecision(r.title,r.message,actions){choice->when(choice){0->toast("نفذ الإجراء في الخدمة ثم عد واضغط متابعة");1->{waitingRequest=null;loop?.resume()};2->loop?.stop()}}
    }

    private fun showDecision(title:String,message:String,actions:List<String>,done:((Int)->Unit)?=null){
        val box=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(24,12,24,8);setBackgroundColor(card)}
        box.addView(tv(title,20f,white,true)); box.addView(tv(message,14f,muted,false))
        actions.forEachIndexed{i,a->box.addView(Button(this).apply{text=a;setOnClickListener{done?.invoke(i)}})}
        AlertDialog.Builder(this).setView(box).setCancelable(false).show()
    }

    private fun showResult(){
        addAssistant("✅ اكتملت المهمة بعد التحقق. النتيجة أصبحت جاهزة للمراجعة.")
        val box=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(16,16,16,16);setBackgroundColor(card)}
        box.addView(tv("النتيجة النهائية",19f,white,true))
        val image=ImageView(this).apply{adjustViewBounds=true;setBackgroundColor(Color.BLACK)}
        box.addView(image,LinearLayout.LayoutParams(-1,280))
        val row=LinearLayout(this)
        row.addView(Button(this).apply{text="اعتماد النتيجة";setOnClickListener{addAssistant("تم اعتماد النتيجة.")}},LinearLayout.LayoutParams(0,56,1f))
        row.addView(Button(this).apply{text="تعديل";setOnClickListener{showRevision()}},LinearLayout.LayoutParams(0,56,1f)); box.addView(row)
        chat.addView(box); UcoaAccessibilityService.instance?.captureScreenshotBase64{b64->runOnUiThread{if(!b64.isNullOrBlank()){val bytes=Base64.decode(b64,Base64.DEFAULT);image.setImageBitmap(BitmapFactory.decodeByteArray(bytes,0,bytes.size))}}}
    }

    private fun showRevision(){
        val e=EditText(this).apply{hint="ما التعديل المطلوب؟";setTextColor(white);setHintTextColor(muted);minLines=4}
        AlertDialog.Builder(this).setTitle("تعديل النتيجة").setMessage("سيتم استهداف الجزء المتأثر وإعادة التحقق قبل إعلان النجاح.").setView(e).setNegativeButton("إلغاء",null).setPositiveButton("حفظ التعديل"){_,_->val q=e.text.toString().trim();if(q.isNotEmpty()){addAssistant("طلب التعديل: $q")}}.show()
    }

    private fun addUser(s:String)=addBubble("أنت\n$s",true)
    private fun addAssistant(s:String)=addBubble("الوكيل\n$s",false)
    private fun addCard(t:String,b:String){val l=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(18,16,18,16);setBackgroundColor(card)};l.addView(tv(t,17f,white,true));l.addView(tv(b,13f,muted,false));chat.addView(l,LinearLayout.LayoutParams(-1,-2).apply{setMargins(0,0,0,12)})}
    private fun addBubble(s:String,user:Boolean){val l=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(16,14,16,14);setBackgroundColor(if(user)Color.rgb(43,38,72)else card)};l.addView(tv(s,14f,white,user));chat.addView(l,LinearLayout.LayoutParams(-1,-2).apply{setMargins(0,0,0,10)})}
    private fun tv(s:String,size:Float,color:Int,bold:Boolean)=TextView(this).apply{text=s;textSize=size;setTextColor(color);setTypeface(null,if(bold)android.graphics.Typeface.BOLD else android.graphics.Typeface.NORMAL);setPadding(2,4,2,4)}
    private fun toast(s:String)=Toast.makeText(this,s,Toast.LENGTH_SHORT).show()
}
