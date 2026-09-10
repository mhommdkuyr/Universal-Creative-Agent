package com.ucoa.app

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.*
import org.json.JSONArray

/**
 * ChatGPT-style RTL shell for UCOA. Keeps planning, approval, accessibility,
 * cloud execution and diagnostics behind the existing engine classes.
 */
class ChatStyleActivity : Activity() {
    private lateinit var brain: AgentBrainClient
    private lateinit var chat: LinearLayout
    private lateinit var input: EditText
    private lateinit var status: TextView
    private lateinit var drawer: LinearLayout
    private var pendingTask: String? = null
    private var pendingPlan: TaskInterpreter.PlanResult? = null
    private var planCard: View? = null
    private var loop: UniversalAgentLoop? = null
    private val bg = Color.rgb(0, 0, 0)
    private val panel = Color.rgb(31, 31, 35)
    private val panel2 = Color.rgb(22, 22, 28)
    private val text = Color.rgb(245, 245, 247)
    private val muted = Color.rgb(164, 164, 171)
    private val blue = Color.rgb(59, 130, 246)
    private val purple = Color.rgb(53, 40, 78)

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        window.decorView.layoutDirection = View.LAYOUT_DIRECTION_RTL
        brain = AgentBrainClient(this)
        UcoaDiagnostics.init(this)
        UcoaDiagnostics.log("UI", "تشغيل واجهة المحادثة الجديدة")
        setContentView(build())
        refreshStatus()
        window.decorView.postDelayed({ permissionGate() }, 450L)
    }

    override fun onResume() { super.onResume(); if (::status.isInitialized) refreshStatus() }

    private fun build(): View {
        val root = FrameLayout(this).apply { setBackgroundColor(bg) }
        val main = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(12, 16, 12, 10) }
        val top = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL }
        val menu = roundButton("☰", 48).apply { setOnClickListener { toggleDrawer(true) } }
        val dots = roundButton("⋯", 48).apply { setOnClickListener { conversationSettings() } }
        val pill = TextView(this).apply { text = "✦  الحصول على Plus"; textSize = 16f; gravity = Gravity.CENTER; setTextColor(Color.rgb(96,165,250)); setBackgroundColor(Color.rgb(38,49,58)); setPadding(14,0,14,0) }
        top.addView(menu, LinearLayout.LayoutParams(48,48)); top.addView(pill, LinearLayout.LayoutParams(0,48,1f).apply{setMargins(12,0,12,0)}); top.addView(dots, LinearLayout.LayoutParams(48,48))
        main.addView(top)
        status = tv("جاري فحص الاتصال…", 12f, muted, Gravity.CENTER); main.addView(status, LinearLayout.LayoutParams(-1,34))
        val scroll = ScrollView(this).apply { layoutParams = LinearLayout.LayoutParams(-1,0,1f); setFillViewport(true) }
        chat = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(8,24,8,24) }
        scroll.addView(chat); main.addView(scroll)
        val suggestions = LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; gravity=Gravity.CENTER_HORIZONTAL }
        suggestion(suggestions,"إنشاء صورة أو ملصق")
        suggestion(suggestions,"الكتابة أو التحرير")
        suggestion(suggestions,"ابحث في الويب")
        chat.addView(suggestions)
        val composer = LinearLayout(this).apply { gravity=Gravity.CENTER_VERTICAL; setPadding(4,4,4,0) }
        val voice = roundButton("◦◦",44).apply { setOnClickListener { startSpeech() } }
        val attach = roundButton("+",44).apply { setOnClickListener { chooseMedia() } }
        input = EditText(this).apply { hint="اسأل الذكاء العملي الكامل"; textSize=17f; setTextColor(text); setHintTextColor(muted); setSingleLine(false); maxLines=4; setBackgroundColor(panel); setPadding(18,8,18,8) }
        val send = roundButton("↑",44).apply { setOnClickListener { startTask() } }
        composer.addView(voice,LinearLayout.LayoutParams(44,52)); composer.addView(input,LinearLayout.LayoutParams(0,56,1f).apply{setMargins(6,0,6,0)}); composer.addView(attach,LinearLayout.LayoutParams(44,52)); composer.addView(send,LinearLayout.LayoutParams(44,52)); main.addView(composer)
        root.addView(main)
        drawer = buildDrawer(); drawer.visibility=View.GONE; root.addView(drawer,FrameLayout.LayoutParams(330,-1,Gravity.START))
        return root
    }

    private fun buildDrawer(): LinearLayout {
        val d=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(18,28,18,18);setBackgroundColor(Color.rgb(17,17,22));layoutDirection=View.LAYOUT_DIRECTION_RTL}
        val head=LinearLayout(this).apply{gravity=Gravity.CENTER_VERTICAL}
        head.addView(tv("المحادثات",24f,text,Gravity.RIGHT),LinearLayout.LayoutParams(0,54,1f)); head.addView(roundButton("×",44).apply{setOnClickListener{toggleDrawer(false)}})
        d.addView(head)
        val search=EditText(this).apply{hint="بحث في المحادثات";setHintTextColor(muted);setTextColor(text);setBackgroundColor(panel);setPadding(16,0,16,0)}; d.addView(search,LinearLayout.LayoutParams(-1,50).apply{setMargins(0,10,0,12)})
        listOf("مهمة جديدة","بحث عن حلقة سولفليكس","تحرير فيديو في CapCut","إنشاء صورة للمنتج","مقارنة أسعار").forEach{v->val b=TextView(this).apply{text=v;textSize=16f;setTextColor(text);gravity=Gravity.CENTER_VERTICAL;setPadding(16,0,16,0);setBackgroundColor(panel2);setOnClickListener{toggleDrawer(false)}};d.addView(b,LinearLayout.LayoutParams(-1,54).apply{setMargins(0,0,0,7)})}
        d.addView(space(8))
        d.addView(menuRow("▦  مكتبة التطبيقات المرتبطة"){appsLibrary()})
        d.addView(menuRow("⚙  الإعدادات"){appSettings()})
        d.addView(space(0),LinearLayout.LayoutParams(1,0,1f))
        d.addView(menuRow("◉  التشخيص والتتبع"){diagnostics()})
        return d
    }

    private fun menuRow(label:String, click:()->Unit):View=TextView(this).apply{text=label;textSize=16f;setTextColor(text);gravity=Gravity.CENTER_VERTICAL;setPadding(16,0,16,0);setBackgroundColor(panel);setOnClickListener{click()}}
    private fun suggestion(parent:LinearLayout,label:String){val b=TextView(this).apply{text=label+"   ›";textSize=16f;setTextColor(text);gravity=Gravity.CENTER_VERTICAL;setPadding(16,0,16,0);setBackgroundColor(Color.TRANSPARENT)};parent.addView(b,LinearLayout.LayoutParams(-1,52))}
    private fun space(h:Int)=Space(this).apply{minimumHeight=h}
    private fun tv(s:String,z:Float,c:Int,g:Int)=TextView(this).apply{text=s;textSize=z;setTextColor(c);gravity=g}
    private fun roundButton(s:String,d:Int)=TextView(this).apply{text=s;textSize=24f;gravity=Gravity.CENTER;setTextColor(text);setBackgroundColor(panel)}

    private fun toggleDrawer(show:Boolean){drawer.visibility=if(show)View.VISIBLE else View.GONE;UcoaDiagnostics.log("NAV","drawer=$show")}

    private fun refreshStatus(){
        brain.readiness{transport,ready,detail->runOnUiThread{val access=PermissionCoordinator.isAccessibilityEnabled(this);val live=PermissionCoordinator.isServiceLive();status.text=when{!access->"○ يحتاج إذن التحكم — افتح الإذن من الخطة عند الطلب";!live->"○ إذن الوصول مفعّل — الخدمة تحتاج تشغيلًا";transport&&ready->"● Cloud Brain متصل • التحكم متاح";else->"○ $detail"}}}
    }

    private fun permissionGate(){if(PermissionCoordinator.isAccessibilityEnabled(this))return;AlertDialog.Builder(this).setTitle("إعداد التحكم أول مرة").setMessage("يحتاج الوكيل إلى خدمة إمكانية الوصول ليتمكن من رؤية الشاشة وتنفيذ النقر والكتابة والفتح. لن يبدأ التنفيذ تلقائيًا قبل موافقتك.").setNegativeButton("لاحقًا",null).setPositiveButton("فتح الأذونات"){_,_->PermissionCoordinator.openAccessibilitySettings(this)}.show()}

    private fun startTask(){
        val task=input.text.toString().trim();if(task.isEmpty())return
        pendingTask=task;input.setText("");addBubble("أنت\n$task",true);UcoaDiagnostics.log("TASK","استلام مهمة",task);addBubble("الوكيل\nأفهم طلبك وأبني خطة قابلة للمراجعة…",false)
        val fallback=TaskInterpreter().analyze(task,emptyList())
        brain.plan(task,emptyList()){r->runOnUiThread{
            val p=if(r.ok&&r.body!=null){val arr=r.body.optJSONArray("steps");val steps=mutableListOf<String>();if(arr!=null)for(i in 0 until arr.length())steps+=arr.optString(i);if(steps.isNotEmpty())fallback.copy(summary=r.body.optString("summary",fallback.summary),steps=steps)else fallback}else fallback
            pendingPlan=p;addBubble("الوكيل\n${if(r.ok)"الخطة جاهزة. لن أنفذ شيئًا قبل الموافقة." else "تعذر الوصول إلى المخطط السحابي؛ أعرض الخطة المحلية للمراجعة."}",false);showPlan(p)
        }}
    }

    private fun showPlan(p:TaskInterpreter.PlanResult){planCard?.let{chat.removeView(it)};val box=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(18,18,18,18);setBackgroundColor(panel2)};box.addView(tv("خطة التنفيذ",19f,text,Gravity.RIGHT));box.addView(tv(p.summary,14f,muted,Gravity.RIGHT));box.addView(tv(p.steps.mapIndexed{i,s->"${i+1}. $s"}.joinToString("\n"),15f,text,Gravity.RIGHT).apply{setPadding(0,14,0,14)});box.addView(tv("الأذونات والموافقات",16f,text,Gravity.RIGHT));box.addView(tv(if(PermissionCoordinator.isAccessibilityEnabled(this))"✓ خدمة الوصول مفعلة" else "! خدمة الوصول مطلوبة للتحكم في الهاتف",14f,if(PermissionCoordinator.isAccessibilityEnabled(this))Color.rgb(74,222,128) else Color.rgb(251,191,36),Gravity.RIGHT));val row=LinearLayout(this).apply{gravity=Gravity.CENTER_VERTICAL};row.addView(Button(this).apply{text="موافقة وتنفيذ";setOnClickListener{approveAndExecute()}},LinearLayout.LayoutParams(0,54,1f));row.addView(Button(this).apply{text="مراجعة";setOnClickListener{editPlan()}},LinearLayout.LayoutParams(0,54,1f));box.addView(row);if(!PermissionCoordinator.isAccessibilityEnabled(this))box.addView(Button(this).apply{text="فتح الأذونات";setOnClickListener{PermissionCoordinator.openAccessibilitySettings(this@ChatStyleActivity)}});chat.addView(box,LinearLayout.LayoutParams(-1,-2).apply{setMargins(0,8,0,12)});planCard=box}

    private fun editPlan(){val p=pendingPlan?:return;val e=EditText(this).apply{setText(p.steps.mapIndexed{i,s->"${i+1}. $s"}.joinToString("\n"));minLines=7;setTextColor(text);setHintTextColor(muted)};AlertDialog.Builder(this).setTitle("مراجعة الخطة").setMessage("يمكنك تعديل الخطوات. الحفظ لا يبدأ التنفيذ.").setView(e).setNegativeButton("إلغاء",null).setPositiveButton("حفظ"){_,_->val steps=e.text.toString().lines().map{it.trim()}.filter{it.isNotEmpty()}.map{it.replaceFirst(Regex("^\\d+\\.\\s*"),"")};if(steps.isNotEmpty()){pendingPlan=p.copy(steps=steps);showPlan(pendingPlan!!)}}.show()}

    private fun approveAndExecute(){val task=pendingTask?:return;val p=pendingPlan?:return;if(!PermissionCoordinator.isAccessibilityEnabled(this)||!PermissionCoordinator.isServiceLive()){addBubble("الوكيل\nأحتاج تفعيل صلاحية الوصول وتشغيل خدمة التحكم أولًا. لم يتم تنفيذ أي خطوة.",false);PermissionCoordinator.openAccessibilitySettings(this);return};addBubble("الوكيل\n✓ تمت الموافقة. أبدأ التنفيذ الآن وأعرض التقدم خطوة بخطوة.",false);UcoaDiagnostics.log("APPROVAL","approved=true");val approved=task+"\nالخطة المعتمدة:\n"+p.steps.mapIndexed{i,s->"${i+1}. $s"}.joinToString("\n");loop=UniversalAgentLoop(brain);loop!!.start(approved,object:UniversalAgentLoop.Listener{override fun onEvent(t:String){runOnUiThread{status.text=t.take(180);addBubble("الوكيل\n$t",false)}}override fun onHumanIntervention(r:HumanIntervention.Request){runOnUiThread{decision(r.title,r.message,listOf(r.actionLabel,"إلغاء")){i->if(i==0)loop?.resume()else loop?.stop()}}}override fun onConfirmationRequired(reasons:String){runOnUiThread{decision("تأكيد مطلوب",reasons,listOf("متابعة","إلغاء")){i->if(i==0)loop?.resume()else loop?.stop()}}}override fun onFinished(ok:Boolean){runOnUiThread{addBubble("الوكيل\n${if(ok)"✓ اكتملت المهمة بعد التحقق." else "توقفت المهمة قبل إثبات الاكتمال."}",false);status.text=if(ok)"● اكتملت المهمة" else "○ تحتاج مراجعة"}}})}

    private fun decision(title:String,message:String,actions:List<String>,done:(Int)->Unit){val box=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(22,12,22,8)};box.addView(tv(title,20f,text,Gravity.RIGHT));box.addView(tv(message,14f,muted,Gravity.RIGHT));val dlg=AlertDialog.Builder(this).setView(box).setCancelable(false).create();actions.forEachIndexed{i,a->box.addView(Button(this).apply{text=a;setOnClickListener{dlg.dismiss();done(i)}})};dlg.show()}

    private fun conversationSettings(){AlertDialog.Builder(this).setTitle("إعدادات المحادثة").setItems(arrayOf("إعادة تسمية المحادثة","تغيير النموذج/الموجه","الموافقة مطلوبة قبل التنفيذ","الرؤية وتحليل الشاشة","سجل التنفيذ والتشخيص"),null).show()}
    private fun appSettings(){val b=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(20,8,20,8)};arrayOf("الحساب","النماذج والمحركات","التطبيقات والصلاحيات","التتبع والتشخيص","المظهر: داكن • RTL","عنوان Cloud Brain").forEach{b.addView(Button(this).apply{text=it;setOnClickListener{when(it.text.toString()){"التطبيقات والصلاحيات"->appsLibrary();"التتبع والتشخيص"->diagnostics();"عنوان Cloud Brain"->brainSettings()}}})};AlertDialog.Builder(this).setTitle("الإعدادات").setView(b).setPositiveButton("إغلاق",null).show()}
    private fun brainSettings(){val e=EditText(this).apply{setText(brain.endpoint());setTextColor(text)};AlertDialog.Builder(this).setTitle("Cloud Brain API").setMessage("الخادم يجمع التخطيط والرؤية والمحركات. لا تغيّر العنوان إلا للاختبار.").setView(e).setNegativeButton("إلغاء",null).setPositiveButton("حفظ"){_,_->brain.saveConfig(e.text.toString(),brain.token());refreshStatus()}.show()}
    private fun appsLibrary(){val apps=AppDiscovery.installedLabels(this).take(40);AlertDialog.Builder(this).setTitle("مكتبة التطبيقات المرتبطة").setMessage(if(apps.isEmpty())"لم يتم اكتشاف تطبيقات بعد." else apps.joinToString("\n")).setPositiveButton("إغلاق",null).show()}
    private fun diagnostics(){val d=AlertDialog.Builder(this).setTitle("التشخيص والتتبع").setMessage(UcoaDiagnostics.recentText().takeLast(12000)).setNegativeButton("إغلاق",null).setPositiveButton("نسخ السجل"){_,_->val cm=getSystemService(CLIPBOARD_SERVICE) as android.content.ClipboardManager;cm.setPrimaryClip(android.content.ClipData.newPlainText("UCOA diagnostics",UcoaDiagnostics.recentText()));Toast.makeText(this,"تم نسخ سجل التشخيص",Toast.LENGTH_SHORT).show()};d.show()}
    private fun chooseMedia(){startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply{type="*/*";putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true);addCategory(Intent.CATEGORY_OPENABLE)},401)}
    private fun startSpeech(){try{startActivityForResult(Intent("android.speech.action.RECOGNIZE_SPEECH").apply{putExtra("android.speech.extra.LANGUAGE_MODEL","free_form");putExtra("android.speech.extra.LANGUAGE","ar-SA")},402)}catch(_:Exception){Toast.makeText(this,"التعرف الصوتي غير متاح",Toast.LENGTH_SHORT).show()}}
    override fun onActivityResult(request:Int,result:Int,data:Intent?){super.onActivityResult(request,result,data);if(result!=RESULT_OK||data==null)return;if(request==402)data.getStringArrayListExtra("android.speech.extra.RESULTS")?.firstOrNull()?.let{input.setText(it)}}
    private fun addBubble(s:String,user:Boolean){val b=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(18,14,18,14);setBackgroundColor(if(user)purple else panel2)};b.addView(tv(s,15f,text,Gravity.RIGHT));chat.addView(b,LinearLayout.LayoutParams(-1,-2).apply{setMargins(0,0,0,10)})}
}
