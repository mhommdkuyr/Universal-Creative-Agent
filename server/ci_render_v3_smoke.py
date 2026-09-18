from __future__ import annotations
import base64,json,os,sys,time,urllib.request
from io import BytesIO
from PIL import Image,ImageDraw,ImageFont
BASE=os.getenv("BRAIN_URL","https://ucoa-agent-brain.onrender.com").rstrip("/")
def request(method,path,payload=None,token=None,timeout=30):
    headers={"Content-Type":"application/json"}
    if token: headers["Authorization"]=f"Bearer {token}"
    data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode()
    req=urllib.request.Request(BASE+path,data=data,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode())
def bootstrap():
    master=os.getenv("UCOA_AGENT_TOKEN","").strip()
    if master:return master
    body=request("POST","/v1/client/session",{"install_id":"ci-release-acceptance","app_version":"ci","platform":"github-actions","device":{"runner":"ubuntu-latest"}},timeout=20)
    token=str(body.get("session_token",""))
    if not token:raise RuntimeError(f"client session bootstrap failed: {body}")
    return token
def unwrap(submitted,token):
    if submitted.get("status")=="completed" and isinstance(submitted.get("result"),dict):return submitted["result"]
    jid=str(submitted.get("job_id",""))
    if not jid:raise RuntimeError(f"cloud did not return result or job_id: {submitted}")
    for _ in range(180):
        x=request("GET","/v1/agent/jobs/"+jid,token=token,timeout=20)
        if x.get("status")=="completed":return x["result"]
        if x.get("status")=="failed":raise RuntimeError(x.get("error","job failed"))
        time.sleep(1)
    raise TimeoutError("job timeout")
def screenshot_b64():
    img=Image.new("RGB",(900,500),"white");d=ImageDraw.Draw(img)
    try:font=ImageFont.truetype("DejaVuSans-Bold.ttf",64)
    except Exception:font=ImageFont.load_default()
    d.text((80,70),"UCOA Test Screen",fill="black",font=font);d.rounded_rectangle((260,260,640,390),radius=20,fill="#dddddd",outline="#222222",width=4);d.text((355,300),"CONTINUE",fill="black",font=font)
    out=BytesIO();img.save(out,format="JPEG",quality=90);return base64.b64encode(out.getvalue()).decode()
def live_phone_acceptance():
    install_id=os.getenv("UCOA_REAL_INSTALL_ID","82cc096d702d427ba3aeb28fd90dfc24")
    token=bootstrap_for_install(install_id)
    task=("اختبار قبول حي حقيقي: افتح تطبيق الإعدادات فقط. لا تغيّر أي إعداد. "
          "يجب أن يثبت UCOA من الجهاز نفسه أن شاشة الإعدادات ظهرت عبر Accessibility UI tree "
          "ولقطة الشاشة. فتح متصفح أو بقاء ChatGPT لا يعتبر نجاحًا.")
    payload={
        "kind":"task",
        "task":task,
        "attachments":[],
        "metadata":{
            "qa_suite":"release-acceptance-real-phone",
            "test_suite":"real_device_live_ui_v10",
            "evidence_required":True,
            "no_external_success":True,
        },
    }
    queued=request("POST","/v1/client/commands",payload,token,timeout=30)
    command_id=str(queued.get("command_id",""))
    if not command_id: raise RuntimeError(f"live phone queue failed: {queued}")
    print("REAL_PHONE_COMMAND",json.dumps({"command_id":command_id,"install_id":install_id},ensure_ascii=False))
    last={}
    for i in range(120):
        last=request("GET","/v1/client/commands/"+command_id,token=token,timeout=30)
        cmd=last.get("command") or {}
        status=cmd.get("status")
        print("REAL_PHONE_POLL",i,status)
        if status in {"completed","failed","cancelled"}:
            break
        time.sleep(2)
    print("REAL_PHONE_RESULT",json.dumps(last,ensure_ascii=False))
    cmd=last.get("command") or {}
    if cmd.get("status")!="completed":
        raise RuntimeError(f"real phone command ended with status={cmd.get('status')}")
    if cmd.get("install_id")!=install_id:
        raise RuntimeError("real phone install_id changed")
    result=cmd.get("result") or {}
    if result.get("error"):
        raise RuntimeError(f"real phone result error={result.get('error')}")
    if result.get("completion_verified_by_ucoa") is not True:
        raise RuntimeError("UCOA did not verify completion")
    if result.get("final_foreground")!="com.android.settings":
        raise RuntimeError(f"wrong final foreground: {result.get('final_foreground')}")
    if int(result.get("steps",0) or 0)<=0:
        raise RuntimeError("no device execution steps recorded")
    print("REAL_DEVICE_ACCEPTANCE_PASS")

def bootstrap_for_install(install_id):
    body=request("POST","/v1/client/session",{
        "install_id":install_id,
        "app_version":"qa",
        "platform":"android",
        "device":{"qa":"release-acceptance"},
    },timeout=20)
    token=str(body.get("session_token",""))
    if not token: raise RuntimeError(f"client session bootstrap failed for {install_id}: {body}")
    return token

mode=sys.argv[1];token=bootstrap()
if mode=="plan":
    result=unwrap(request("POST","/v1/agent/plan",{"task":"Open the appropriate app, perform the requested action, and verify the result.","device":{"android":35}},token,timeout=180),token);assert len(result.get("steps",[]))>=2,result;assert result.get("provider") not in {None,"","repair"},result;print("PLAN_V4_OK",json.dumps(result,ensure_ascii=False))
elif mode=="step":
    result=unwrap(request("POST","/v1/agent/step",{"task":"Press the visible CONTINUE button.","step":0,"history":[],"ui_tree":"[{\"text\":\"CONTINUE\",\"class\":\"android.widget.Button\"}]","screenshot_base64":screenshot_b64(),"installed_apps":["Chrome"],"capabilities":["click_any_text","tap","observe","done"]},token,timeout=180),token);provider=str(result.get("vision_provider",""));assert provider not in {"","repair","compatibility"},result;assert result.get("visual_observation"),result;assert result.get("action") in {"click_any_text","tap","observe","done"},result;print("RENDER_V4_MULTIMODAL_OK",json.dumps({"vision_provider":provider,"provider":result.get("provider"),"action":result.get("action"),"visual_observation":result.get("visual_observation")},ensure_ascii=False))
elif mode=="state":
    live_phone_acceptance()
    sid=request("POST","/v1/agent/sessions",{"title":"ci-v4"},token)["session_id"];request("POST","/v1/agent/state",{"session_id":sid,"state":{"task":"smoke","step":2,"status":"verified"}},token);state=request("GET","/v1/agent/state/"+sid,token=token,timeout=20);assert state["state"]["step"]==2;verified=request("POST","/v1/agent/verify-result",{"task":"press continue","action":{"action":"click_any_text","params":{"texts":["CONTINUE"]}},"before_ui_tree":"[{\"text\":\"CONTINUE\"}]","after_ui_tree":"[{\"text\":\"NEXT\"}]","session_id":sid},token);assert verified["verified"] is True,verified;print("RENDER_V4_STATE_VERIFIER_OK",sid)
else:raise SystemExit("unknown mode")
