package com.ucoa.app

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.*

/** Lightweight ChatGPT-style RTL shell. Execution remains behind existing agent/permission engines. */
class ChatStyleActivity : Activity() {
    private lateinit var brain: AgentBrainClient
    private lateinit var chat: LinearLayout
    private lateinit var input: EditText
    private lateinit var status: TextView
    private lateinit var drawer: LinearLayout
    private var task: String? = null
    private var plan: TaskInterpreter.PlanResult? = null
    private var loop: UniversalAgentLoop? = null
    private val ink = Color.rgb(245,245,247)
    private val muted = Color.rgb(164,164,171)
    private val panel = Color.rgb(31,31,35)
    private val panel2 = Color.rgb(22,22,28)
    private val blue = Color.rgb(59,130,246)

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        window.decorView.layoutDirection = View.LAYOUT_DIRECTION_RTL
        brain = AgentBrainClient(this)
        UcoaDiagnostics.init(this)
        setContentView(buildUi())
        refresh()
        window.decorView.postDelayed({ firstPermissionPrompt() }, 500)
    }
    override fun onResume(){ super.onResume(); if(::status.isInitialized) refresh() }

    private fun buildUi(): View {
        val root = FrameLayout(this).apply{setBackgroundColor(Color.BLACK)}
        val main = LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(12,14,12,8)}
        val top=LinearLayout(this).apply{gravity=Gravity.CENTER_VERTICAL;layoutDirection=View.LAYOUT_DIRECTION_RTL}
        top.addView(button("☰",48){drawer.visibility=View.VISIBLE}, LinearLayout.LayoutParams(48,48))
        val plus=TextView(this).apply{text="✦  الحصول على Plus";textSize=16f;gravity=Gravity.CENTER;setTextColor(Color.rgb(96,165,250));setBackgroundColor(Color.rgb(38,49,58))}
        top.addView(plus,LinearLayout.LayoutParams(0,48,1f).apply{setMargins(10,0,10,0)})
        top.addView(button("⋯",48){conversationSettings()},LinearLayout.LayoutParams(48,48))
        main.addView(top)
        status=label("جاري فحص الاتصال…",12f,muted,Gravity.CENTER);main.addView(status,LinearLayout.LayoutParams(-1,32))
        val scroll=ScrollView(this).apply{layoutParams=LinearLayout.LayoutParams(-1,0,1f);setFillViewport(true)}
        chat=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(8,24,8,24)}
        scroll.addView(chat);main.addView(scroll)
        label("كيف يمكنني مساعدتك؟",28f,ink,Gravity.CENTER).also{chat.addView(it,LinearLayout.LayoutParams(-1,70))}
        label("اكتب أي مهمة. سأفهمها، أبني خطة، أعرض الأذونات، ثم أنتظر موافقتك قبل التنفيذ.",15f,muted,Gravity.CENTER).also{chat.addView(it,LinearLayout.LayoutParams(-1,80))}
        listOf("إنشاء صورة أو ملصق","الكتابة أو التحرير","ابحث في الويب").forEach{chat.addView(label("$it   ›",17f,ink,Gravity.RIGHT),LinearLayout.LayoutParams(-1,54))}
        val compose=LinearLayout(this).apply{gravity=Gravity.CENTER_VERTICAL}
        compose.addView(button("◦◦",44){speech()},LinearLayout.LayoutParams(44,52))
        input=EditText(this).apply{hint="اسأل الذكاء العملي الكامل";textSize=17f;setTextColor(ink);setHintTextColor(muted);setBackgroundColor(panel);setPadding(16,0,16,0);maxLines=4}
        compose.addView(input,LinearLayout.LayoutParams(0,56,1f).apply{setMargins(6,0,6,0)})
        compose.addView(button("+",44){media()},LinearLayout.LayoutParams(44,52))
        compose.addView(button("↑",44){submit()},LinearLayout.LayoutParams(44,52))
        main.addView(compose)
        root.addView(main)
        drawer=buildDrawer();drawer.visibility=View.GONE;root.addView(drawer,FrameLayout.LayoutParams(340,-1,Gravity.START))
        return root
    }

    private fun buildDrawer():LinearLayout{
        val d=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(18,24,18,18);setBackgroundColor(Color.rgb(17,17,22));layoutDirection=View.LAYOUT_DIRECTION_RTL}
        d.addView(label("المحادثات",25f,ink,Gravity.RIGHT),LinearLayout.LayoutParams(-1,54))
        d.addView(button("×",44){drawer.visibility=View.GONE},LinearLayout.LayoutParams(-1,44))
        val search=EditText(this).apply{hint="بحث في المحادثات";setHintTextColor(muted);setTextColor(ink);setBackgroundColor(panel);setPadding(14,0,14,0)};d.addView(search,LinearLayout.LayoutParams(-1,50).apply{setMargins(0,8,0,10)})
        listOf("مهمة جديدة","بحث عن حلقة سولفليكس","تحرير فيديو في CapCut","إنشاء صورة للمنتج","مقارنة أسعار").forEach{v->d.addView(label(v,16f,ink,Gravity.RIGHT),LinearLayout.LayoutParams(-1,52).apply{setMargins(0,0,0,6)})}
        d.addView(space(8),LinearLayout.LayoutParams(1,8));d.addView(row("▦  مكتبة التطبيقات المرتبطة"){apps()});d.addView(row("⚙  الإعدادات"){settings()});d.addView(space(1),LinearLayout.LayoutParams(1,0,1f));d.addView(row("◉  التشخيص والتتبع"){diagnostics()});return d
    }
    private fun row(s:String,action:()->Unit)=label(s,16f,ink,Gravity.RIGHT).apply{setPadding(14,0,14,0);setBackgroundColor(panel);setOnClickListener{action()}}
    private fun label(s:String,z:Float,c:Int,g:Int)=TextView(this).apply{text=s;textSize=z;setTextColor(c);gravity=g}
    private fun button(s:String,d:Int,action:()->Unit)=TextView(this).apply{text=s;textSize=23f;gravity=Gravity.CENTER;setTextColor(ink);setBackgroundColor(panel);setOnClickListener{action()}}
    private fun space(h:Int)=Space(this).apply{minimumHeight=h}

    private fun refresh(){brain.readiness{transport,ready,detail->runOnUiThread{status.text=when{!PermissionCoordinator.isAccessibilityEnabled(this)->"○ يحتاج إذن التحكم";!PermissionCoordinator.isServiceLive()->"○ إذن الوصول مفعّل — شغّل الخدمة";transport&&ready->"● Cloud Brain متصل • التنفيذ متاح";else->"○ $detail"}}}}
    private fun firstPermissionPrompt(){if(PermissionCoordinator.isAccessibilityEnabled(this))return;AlertDialog.Builder(this).setTitle("إذن التحكم مطلوب").setMessage("لن ينفذ التطبيق أي خطوة قبل موافقتك. لتفعيل التحكم افتح خدمة إمكانية الوصول.").setNegativeButton("لاحقًا",null).setPositiveButton("فتح الأذونات"){_,_->PermissionCoordinator.openAccessibilitySettings(this)}.show()}

    private fun submit(){val q=input.text.toString().trim();if(q.isEmpty())return;task=q;input.setText("");bubble("أنت\n$q",true);bubble("الوكيل\nأفهم الطلب وأبني خطة قابلة للمراجعة…",false);val local=TaskInterpreter().analyze(q,emptyList());brain.plan(q,emptyList()){r->runOnUiThread{val p=if(r.ok&&r.body!=null){val a=r.body.optJSONArray("steps");val s=mutableListOf<String>();if(a!=null)for(i in 0 until a.length())s+=a.optString(i);if(s.isNotEmpty())local.copy(summary=r.body.optString("summary",local.summary),steps=s)else local}else local;plan=p;bubble("الوكيل\n${if(r.ok)"الخطة جاهزة. لن يبدأ التنفيذ قبل موافقتك." else "المخطط السحابي غير متاح مؤقتًا؛ هذه خطة محلية للمراجعة."}",false);showPlan(p)}}}
    private fun showPlan(p:TaskInterpreter.PlanResult){val box=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(18,18,18,18);setBackgroundColor(panel2)};box.addView(label("خطة التنفيذ",20f,ink,Gravity.RIGHT));box.addView(label(p.summary,14f,muted,Gravity.RIGHT));box.addView(label(p.steps.mapIndexed{i,s->"${i+1}. $s"}.joinToString("\n"),15f,ink,Gravity.RIGHT).apply{setPadding(0,14,0,14)});box.addView(label("الأذونات والموافقات",17f,ink,Gravity.RIGHT));val access=PermissionCoordinator.isAccessibilityEnabled(this);box.addView(label(if(access)"✓ خدمة الوصول مفعلة" else "! يحتاج صلاحية الوصول والتحكم",14f,if(access)Color.rgb(74,222,128) else Color.rgb(251,191,36),Gravity.RIGHT));val approve=Button(this).apply{text="موافقة وتنفيذ";setOnClickListener{approveExecute()}};val review=Button(this).apply{text="مراجعة الخطة";setOnClickListener{editPlan()}};box.addView(approve);box.addView(review);if(!access)box.addView(Button(this).apply{text="فتح الأذونات";setOnClickListener{PermissionCoordinator.openAccessibilitySettings(this@ChatStyleActivity)}});chat.addView(box,LinearLayout.LayoutParams(-1,-2).apply{setMargins(0,10,0,12)})}
    private fun editPlan(){val p=plan?:return;val e=EditText(this).apply{setText(p.steps.mapIndexed{i,s->"${i+1}. $s"}.joinToString("\n"));setTextColor(ink);setHintTextColor(muted);minLines=7};AlertDialog.Builder(this).setTitle("مراجعة الخطة").setMessage("التعديل لا يبدأ التنفيذ.").setView(e).setNegativeButton("إلغاء",null).setPositiveButton("حفظ"){_,_->val s=e.text.toString().lines().map{it.trim()}.filter{it.isNotEmpty()}.map{it.replaceFirst(Regex("^\\d+\\.\\s*"),"")};if(s.isNotEmpty()){plan=p.copy(steps=s);showPlan(plan!!)}}.show()}
    private fun approveExecute(){val q=task?:return;val p=plan?:return;if(!PermissionCoordinator.isAccessibilityEnabled(this)||!PermissionCoordinator.isServiceLive()){bubble("الوكيل\nلم أبدأ التنفيذ: فعّل إذن الوصول وشغّل الخدمة أولًا.",false);PermissionCoordinator.openAccessibilitySettings(this);return};bubble("الوكيل\n✓ تمت الموافقة. أبدأ التنفيذ مع التحقق بعد كل خطوة.",false);val approved=q+"\nالخطة المعتمدة:\n"+p.steps.mapIndexed{i,s->"${i+1}. $s"}.joinToString("\n");loop=UniversalAgentLoop(brain);loop!!.start(approved,object:UniversalAgentLoop.Listener{override fun onEvent(t:String){runOnUiThread{status.text=t.take(180);bubble("الوكيل\n$t",false)}}override fun onHumanIntervention(r:HumanIntervention.Request){runOnUiThread{confirm(r.title,r.message,r.actionLabel){loop?.resume()}}}override fun onConfirmationRequired(r:String){runOnUiThread{confirm("تأكيد مطلوب",r,"متابعة"){loop?.resume()}}}override fun onFinished(ok:Boolean){runOnUiThread{bubble("الوكيل\n${if(ok)"✓ اكتملت المهمة وتم التحقق." else "توقفت المهمة قبل إثبات الاكتمال."}",false)}}})}
    private fun confirm(title:String,msg:String,yes:String,go:()->Unit){AlertDialog.Builder(this).setTitle(title).setMessage(msg).setNegativeButton("إلغاء"){_,_->loop?.stop()}.setPositiveButton(yes){_,_->go()}.setCancelable(false).show()}
    private fun bubble(s:String,user:Boolean){val b=TextView(this).apply{text=s;textSize=15f;setTextColor(ink);setPadding(18,14,18,14);setBackgroundColor(if(user)Color.rgb(53,40,78) else panel2)};chat.addView(b,LinearLayout.LayoutParams(-1,-2).apply{setMargins(0,0,0,8)})}
    private fun conversationSettings(){AlertDialog.Builder(this).setTitle("إعدادات المحادثة").setItems(arrayOf("إعادة تسمية","النموذج والمحركات","الموافقة مطلوبة قبل التنفيذ","الرؤية وتحليل الشاشة","سجل التنفيذ والتشخيص"),null).show()}
    private fun settings(){AlertDialog.Builder(this).setTitle("الإعدادات").setItems(arrayOf("الحساب","النماذج والمحركات","التطبيقات والصلاحيات","التتبع والتشخيص","المظهر: داكن • RTL","عنوان Cloud Brain")){_,which->when(which){2->apps();3->diagnostics()}}.show()}
    private fun apps(){val a=AppDiscovery.installedLabels(this).take(50);AlertDialog.Builder(this).setTitle("مكتبة التطبيقات المرتبطة").setMessage(if(a.isEmpty())"لا توجد تطبيقات مكتشفة." else a.joinToString("\n")).setPositiveButton("إغلاق",null).show()}
    private fun diagnostics(){val s=UcoaDiagnostics.recentText();AlertDialog.Builder(this).setTitle("التشخيص والتتبع").setMessage(s.takeLast(12000)).setPositiveButton("إغلاق",null).setNeutralButton("نسخ السجل"){_,_->val cm=getSystemService(CLIPBOARD_SERVICE) as ClipboardManager;cm.setPrimaryClip(ClipData.newPlainText("UCOA diagnostics",s))}.show()}
    private fun media(){startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply{type="*/*";addCategory(Intent.CATEGORY_OPENABLE);putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true)},401)}
    private fun speech(){try{startActivityForResult(Intent("android.speech.action.RECOGNIZE_SPEECH").apply{putExtra("android.speech.extra.LANGUAGE_MODEL","free_form");putExtra("android.speech.extra.LANGUAGE","ar-SA")},402)}catch(_:Exception){}}
    override fun onActivityResult(r:Int,c:Int,d:Intent?){super.onActivityResult(r,c,d);if(c==RESULT_OK&&r==402)d?.getStringArrayListExtra("android.speech.extra.RESULTS")?.firstOrNull()?.let{input.setText(it)}}
}
