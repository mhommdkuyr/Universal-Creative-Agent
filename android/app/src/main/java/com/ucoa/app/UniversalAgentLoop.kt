package com.ucoa.app

import android.os.Handler
import android.os.Looper
import org.json.JSONArray
import org.json.JSONObject

/** Observe -> decide -> recover -> act -> verify, with durable human checkpoints. */
class UniversalAgentLoop(private val brain: AgentBrainClient) {
    interface Listener {
        fun onEvent(text: String)
        fun onFinished(success: Boolean)
        fun onConfirmationRequired(reasons: String) { onEvent("تأكيد مطلوب قبل التنفيذ: $reasons") }
        fun onHumanIntervention(request: HumanIntervention.Request) { onEvent("تدخل المستخدم مطلوب: ${request.title}") }
    }
    private val main=Handler(Looper.getMainLooper()); private var running=false; private var waiting=false
    private var task=""; private var step=0; private var listener:Listener?=null; private var history=JSONArray(); private var attachments:List<String>=emptyList(); private var recoveryAttempts=0

    fun start(taskText:String, listener:Listener, selectedAttachments:List<String>=emptyList()) {
        if(running||waiting)return
        if(UcoaAccessibilityService.instance==null){listener.onEvent("خدمة التحكم غير متاحة");listener.onFinished(false);return}
        running=true; waiting=false; task=taskText; step=0; recoveryAttempts=0; history=JSONArray(); this.listener=listener; attachments=selectedAttachments
        UcoaDiagnostics.log("AGENT","بدأت دورة الوكيل","task=${task.take(500)}"); listener.onEvent("بدأ الوكيل: الإدراك ← القرار ← حل المشكلة ← التنفيذ ← التحقق."); persist("running"); next()
    }

    fun resume(){ if(waiting){ waiting=false; running=true; recoveryAttempts=0; persist("resumed"); listener?.onEvent("استئناف المهمة من نقطة التوقف المحفوظة."); next() } }
    fun stop(){running=false;waiting=false;persist("stopped");listener?.onEvent("تم إيقاف المهمة.")}
    fun isWaitingForHuman()=waiting

    private fun next(){
        if(!running)return
        if(step>=60){finish(false,"تم استنفاد الحد الآمن لخطوات التنفيذ.");return}
        val service=UcoaAccessibilityService.instance?:run{finish(false,"فقدت خدمة التحكم.");return}
        if(step==0){requestedAppName(task)?.let{ if(service.openAppByName(it)){history.put(JSONObject().apply{put("step",0);put("action","open_app_by_name");put("ok",true)});step=1;persist("opened_$it");main.postDelayed({next()},1200);return} }}
        service.captureScreenshotBase64{beforeScreenshot->
            if(!running)return@captureScreenshotBase64
            val beforeUi=service.observeUi(320)
            brain.step(task,step,history,beforeUi,beforeScreenshot,service.installedAppLabels(),attachments,false){response->main.post{
                if(!running)return@post
                if(!response.ok||response.body==null){
                    recoveryAttempts++
                    UcoaDiagnostics.log("RECOVERY","فشل القرار — محاولة استرداد","attempt=$recoveryAttempts error=${response.error}")
                    if(recoveryAttempts<3){listener?.onEvent("أواجه مشكلة مؤقتة؛ سأعيد الملاحظة وأحاول حلها تلقائيًا.");main.postDelayed({next()},1000L*recoveryAttempts);return@post}
                    finish(false,"لم أستطع حل المشكلة تلقائيًا بعد عدة محاولات آمنة.");return@post
                }
                recoveryAttempts=0
                val decision=response.body; val vp=decision.optString("vision_provider"); val summary=decision.optJSONObject("visual_observation")?.optString("screen_summary","").orEmpty()
                if(summary.isNotBlank())listener?.onEvent("الرؤية: $summary")
                decision.optString("message").takeIf{it.isNotBlank()}?.let{listener?.onEvent("العقل: $it")}
                HumanIntervention.detect(decision,summary)?.let{ req-> waiting=true;running=false;persist("waiting_${req.kind}");UcoaDiagnostics.log("HUMAN","المهمة تحتاج تدخلًا بشريًا","kind=${req.kind} step=$step");listener?.onHumanIntervention(req);return@post }
                val verification=decision.optJSONObject("verification")
                if(verification?.optBoolean("requires_confirmation",false)==true){val reasons=verification.optJSONArray("reasons")?.let{a->(0 until a.length()).joinToString(", "){a.optString(it)}}?:"policy";listener?.onConfirmationRequired(reasons);finish(false,"تم إيقاف التنفيذ الآلي حفاظًا على الأمان.");return@post}
                val action=decision.optString("action").trim(); val params=decision.optJSONObject("params")?:decision
                if(decision.optBoolean("done",false)||action.equals("done",true)){finish(true,decision.optString("message","اكتملت المهمة."));return@post}
                if(action.isBlank()){recoveryAttempts++;if(recoveryAttempts<3){listener?.onEvent("لم أحصل على إجراء صالح؛ سأعيد الملاحظة تلقائيًا.");main.postDelayed({next()},800);return@post};finish(false,"تعذر الحصول على إجراء صالح.");return@post}
                execute(action,params){ok,detail->main.post{afterAction(beforeUi,beforeScreenshot,action,decision,ok,detail)}}
            }}
        }
    }

    private fun requestedAppName(text:String):String?{val t=text.lowercase();return listOf("capcut" to "CapCut","كاب كات" to "CapCut","كابكات" to "CapCut","youtube" to "YouTube","يوتيوب" to "YouTube","canva" to "Canva","كانفا" to "Canva","chrome" to "Chrome","كروم" to "Chrome","instagram" to "Instagram","انستجرام" to "Instagram","واتساب" to "WhatsApp","whatsapp" to "WhatsApp","telegram" to "Telegram","تليجرام" to "Telegram").firstOrNull{t.contains(it.first)}?.second}

    private fun afterAction(beforeUi:String,beforeScreenshot:String?,action:String,decision:JSONObject,ok:Boolean,detail:String){
        val service=UcoaAccessibilityService.instance?:run{finish(false,"فقدت خدمة التحكم أثناء التحقق.");return}
        history.put(JSONObject().apply{put("step",step);put("action",action);put("ok",ok);put("detail",detail.take(700))});persist("step_$step")
        if(!ok){recoveryAttempts++;listener?.onEvent("تعذر تنفيذ الخطوة؛ سأبحث عن طريقة أخرى تلقائيًا.");if(recoveryAttempts<3){main.postDelayed({next()},700L*recoveryAttempts);return};finish(false,"تعذر حل خطوة التنفيذ بعد عدة محاولات.");return}
        service.captureScreenshotBase64{afterScreenshot->val afterUi=service.observeUi(320);brain.verifyResult(task,decision,beforeUi,afterUi,beforeScreenshot,afterScreenshot){result->main.post{
            if(!running)return@post
            val verified=result.ok&&(result.body?.optBoolean("verified",false)?:false)
            if(verified){recoveryAttempts=0;listener?.onEvent("تم التحقق من نجاح الخطوة.");step++;persist("verified_$step");main.postDelayed({next()},decision.optLong("wait_after_ms",700L).coerceIn(150L,5000L))}
            else{recoveryAttempts++;listener?.onEvent("لم يثبت النجاح؛ سأعيد الملاحظة وأحاول تصحيح المسار.");if(recoveryAttempts>=3){listener?.onEvent("سأطلب تدخل المستخدم فقط إذا لم يتوفر حل آلي آخر.");recoveryAttempts=0};main.postDelayed({next()},600L)}
        }}}
    }

    private fun execute(action:String,p:JSONObject,cb:(Boolean,String)->Unit){val s=UcoaAccessibilityService.instance?:run{cb(false,"service_offline");return};when(action.lowercase()){
        "open_url"->cb(s.openUrl(p.optString("url")),"");"open_app_by_name"->cb(s.openAppByName(p.optString("app_name")),p.optString("app_name"));"click_any_text"->cb(s.clickAnyText(array(p,"texts","text")),"");"type_into_any"->cb(s.typeIntoAny(array(p,"hints"),p.optString("text")),"");"share_attachment"->{val i=p.optInt("index",0);val a=attachments.getOrNull(i);if(a==null)cb(false,"attachment_index_missing=$i")else cb(s.shareAttachment(a,p.optString("target_package").takeIf{it.isNotBlank()}),"attachment_$i")};
        "tap"->cb(s.tap(p.optDouble("x").toFloat(),p.optDouble("y").toFloat()),"");"long_press"->cb(s.longPress(p.optDouble("x").toFloat(),p.optDouble("y").toFloat(),p.optLong("duration_ms",700)),"");"swipe"->cb(s.swipe(p.optDouble("x1").toFloat(),p.optDouble("y1").toFloat(),p.optDouble("x2").toFloat(),p.optDouble("y2").toFloat(),p.optLong("duration_ms",500)),"");"back"->cb(s.back(),"");"home"->cb(s.home(),"");"wait"->main.postDelayed({cb(true,"waited")},p.optLong("ms",1000).coerceIn(100,10000));"observe"->cb(true,s.observeUi(320));else->cb(false,"unsupported_action=$action")}}
    private fun array(o:JSONObject,k:String,f:String?):List<String>{val out=mutableListOf<String>();o.optJSONArray(k)?.let{a->for(i in 0 until a.length())out+=a.optString(i)};if(out.isEmpty()&&f!=null)o.optString(f).takeIf{it.isNotBlank()}?.let{out+=it};return out}
    private fun persist(status:String){brain.persistExecutionState(task,step,history,status)}
    private fun finish(success:Boolean,message:String){running=false;waiting=false;persist(if(success)"completed"else"failed");listener?.onEvent(message);listener?.onFinished(success)}
}
