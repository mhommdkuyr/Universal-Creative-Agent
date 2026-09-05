from __future__ import annotations

import base64, json, os, re, sqlite3, tempfile, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="UCOA Universal Agent Brain", version="3.0.0")
ACTIONS = ["open_url","open_app_by_name","click_any_text","type_into_any","share_attachment","tap","long_press","swipe","back","home","wait","observe","done"]
LOCAL_BASE = os.getenv("UCOA_MODEL_BASE_URL", "").rstrip("/")
LOCAL_MODEL = os.getenv("UCOA_MODEL_NAME", "Qwen2.5-0.5B-Instruct-Q2_K")
LOCAL_KEY = os.getenv("UCOA_MODEL_API_KEY", "")
HF_BASE = os.getenv("UCOA_HF_ROUTER_URL", "https://router.huggingface.co/v1").rstrip("/")
HF_TOKEN = os.getenv("HF_TOKEN", "")
REASONING_MODEL = os.getenv("UCOA_REASONING_MODEL", "Qwen/Qwen3-4B-Instruct-2507")
VISION_MODEL = os.getenv("UCOA_VISION_MODEL", "Qwen/Qwen3-VL-2B-Instruct")
VISION_SPACE = os.getenv("UCOA_VISION_SPACE_URL", "https://akhaliq-qwen3-vl-2b-instruct.hf.space").rstrip("/")
VISION_ENABLED = os.getenv("UCOA_LOCAL_VISION", "true").lower() == "true"
EXT_BASE = os.getenv("UCOA_FALLBACK_BASE_URL", "").rstrip("/")
EXT_MODEL = os.getenv("UCOA_FALLBACK_MODEL", "")
EXT_KEY = os.getenv("UCOA_FALLBACK_API_KEY", "")
AGENT_TOKEN = os.getenv("UCOA_AGENT_TOKEN", "")
DB_PATH = Path(os.getenv("UCOA_STATE_DB", "/opt/render/project/src/.ucoa-local/state.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

JOBS: dict[str, dict[str, Any]] = {}; JOB_LOCK = threading.Lock(); DB_LOCK = threading.Lock(); EXECUTOR = ThreadPoolExecutor(max_workers=2)

class PlanRequest(BaseModel):
    task: str; attachments: list[str] = Field(default_factory=list); device: dict[str, Any] = Field(default_factory=dict); session_id: str | None = None
class StepRequest(BaseModel):
    task: str; step: int = 0; max_steps: int = 60; history: list[dict[str, Any]] = Field(default_factory=list); ui_tree: str = "[]"; screenshot_base64: str | None = None; installed_apps: list[str] = Field(default_factory=list); attachments: list[str] = Field(default_factory=list); capabilities: list[str] = Field(default_factory=lambda: ACTIONS.copy()); session_id: str | None = None; approved_risks: bool = False
class VerifyRequest(BaseModel):
    task: str; decision: dict[str, Any]; approved_risks: bool = False; session_id: str | None = None
class ResultVerifyRequest(BaseModel):
    task: str; action: dict[str, Any]; before_ui_tree: str = "[]"; after_ui_tree: str = "[]"; before_screenshot_base64: str | None = None; after_screenshot_base64: str | None = None; session_id: str | None = None
class SessionRequest(BaseModel):
    session_id: str | None = None; title: str = "UCOA session"
class StateRequest(BaseModel):
    session_id: str; state: dict[str, Any] = Field(default_factory=dict)

SENSITIVE = ["password","passcode","pin","otp","verification code","token","card number","cvv","كلمة المرور","رمز التحقق","بطاقة","شراء","دفع","حذف","تحويل","pay","delete"]

def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=15); c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,title TEXT,created_at REAL,updated_at REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,session_id TEXT,kind TEXT,payload TEXT,created_at REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS states(session_id TEXT PRIMARY KEY,state TEXT,updated_at REAL)"); c.commit(); return c

def ensure_session(sid: str | None, title: str = "UCOA session") -> str:
    sid = sid or uuid.uuid4().hex; now = time.time()
    with DB_LOCK:
        c = db(); c.execute("INSERT OR IGNORE INTO sessions VALUES(?,?,?,?)", (sid,title,now,now)); c.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now,sid)); c.commit(); c.close()
    return sid

def remember(sid: str | None, kind: str, payload: Any) -> str:
    sid = ensure_session(sid); now = time.time()
    with DB_LOCK:
        c=db(); c.execute("INSERT INTO events VALUES(?,?,?,?,?)", (uuid.uuid4().hex,sid,kind,json.dumps(payload,ensure_ascii=False),now)); c.execute("UPDATE sessions SET updated_at=? WHERE id=?",(now,sid)); c.commit(); c.close()
    return sid

def memory(sid: str | None, limit: int = 24) -> list[dict[str,Any]]:
    if not sid: return []
    ensure_session(sid)
    with DB_LOCK:
        c=db(); rows=c.execute("SELECT kind,payload FROM events WHERE session_id=? ORDER BY created_at DESC LIMIT ?",(sid,min(max(limit,1),64))).fetchall(); c.close()
    out=[]
    for kind,payload in reversed(rows):
        try: x=json.loads(payload); out.append({"kind":kind,**x} if isinstance(x,dict) else {"kind":kind,"value":x})
        except Exception: out.append({"kind":kind,"text":payload})
    return out

def save_state(sid: str, state: dict[str,Any]) -> None:
    ensure_session(sid); now=time.time()
    with DB_LOCK:
        c=db(); c.execute("INSERT INTO states VALUES(?,?,?) ON CONFLICT(session_id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at",(sid,json.dumps(state,ensure_ascii=False),now)); c.commit(); c.close()

def load_state(sid: str | None) -> dict[str,Any]:
    if not sid: return {}
    ensure_session(sid)
    with DB_LOCK:
        c=db(); row=c.execute("SELECT state FROM states WHERE session_id=?",(sid,)).fetchone(); c.close()
    if not row: return {}
    try:return json.loads(row[0])
    except:return {}

def auth(a: str|None)->None:
    if AGENT_TOKEN and a != f"Bearer {AGENT_TOKEN}": raise HTTPException(401,"Invalid agent token")

def extract_json(t: str)->dict[str,Any]:
    t=t.strip(); t=re.sub(r"^```(?:json)?\s*|\s*```$","",t)
    try:
        x=json.loads(t)
        if isinstance(x,dict): return x
    except: pass
    m=re.search(r"\{.*\}",t,re.S)
    if m:
        x=json.loads(m.group(0));
        if isinstance(x,dict): return x
    raise ValueError("no JSON object")

def chat(base,key,model,system,user,image=None,timeout=120):
    if not base or not model: raise RuntimeError("provider not configured")
    content=user if not image else [{"type":"text","text":user},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{image}"}}]
    payload={"model":model,"temperature":0,"max_tokens":int(os.getenv("UCOA_MAX_TOKENS","96")),"messages":[{"role":"system","content":system},{"role":"user","content":content}]}
    u=base if base.endswith("/chat/completions") else base+"/chat/completions"; h={"Content-Type":"application/json"}
    if key: h["Authorization"]=f"Bearer {key}"
    try:
        with urlopen(Request(u,data=json.dumps(payload,ensure_ascii=False).encode(),headers=h,method="POST"),timeout=timeout) as r: body=json.loads(r.read().decode())
    except (HTTPError,URLError,TimeoutError) as e: raise RuntimeError(str(e))
    return str(body.get("choices",[{}])[0].get("message",{}).get("content",""))

def vision_space(prompt,image):
    from gradio_client import Client,handle_file
    raw=base64.b64decode(image)
    with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
        f.write(raw); f.flush(); c=Client(VISION_SPACE,verbose=False); return str(c.predict({"text":prompt,"files":[handle_file(f.name)]},[],api_name="/qwen_chat_fn"))

def visual(task,ui,image):
    sys="You are UCOA visual perception. Inspect only the pixels/UI. Do not choose an action. Return JSON {screen_summary:string,elements:[{text,role,x,y}],visible_goal_state:string,confidence:number}. Never invent unseen elements."
    prompt=json.dumps({"task":task,"ui_tree":ui[:14000]},ensure_ascii=False)
    if HF_TOKEN:
        try:return extract_json(chat(HF_BASE,HF_TOKEN,VISION_MODEL,sys,prompt,image,150)),"huggingface-router"
        except:pass
    raw=vision_space(sys+"\n"+prompt,image)
    try:return extract_json(raw),"huggingface-space"
    except:return {"screen_summary":re.sub(r"\s+"," ",raw)[:1200],"elements":[],"visible_goal_state":"unknown","confidence":0.35},"huggingface-space"

def call_vision(task, ui, image):
    """Backward-compatible hook that resolves the current visual function dynamically."""
    return visual(task, ui, image)

def reasoning(system,user):
    if HF_TOKEN:
        try:return chat(HF_BASE,HF_TOKEN,REASONING_MODEL,system,user,None,150),"huggingface-router"
        except:pass
    if EXT_BASE and EXT_MODEL:
        try:return chat(EXT_BASE,EXT_KEY,EXT_MODEL,system,user,None,150),"external-fallback"
        except:pass
    return chat(LOCAL_BASE,LOCAL_KEY,LOCAL_MODEL,system,user,None,int(os.getenv("UCOA_MODEL_TIMEOUT","180"))),"render-local"

def safety(task,decision,approved=False):
    act=str(decision.get("action","observe")); p=decision.get("params") if isinstance(decision.get("params"),dict) else {}; text=(task+" "+json.dumps(p,ensure_ascii=False)).lower(); reasons=[]
    if act not in ACTIONS: reasons.append("unsupported_action")
    if act=="share_attachment": reasons.append("external_share")
    if act=="type_into_any" and any(w in text for w in SENSITIVE): reasons.append("sensitive_input")
    if any(w in text for w in SENSITIVE) and act in {"tap","click_any_text","type_into_any","open_url","open_app_by_name"}: reasons.append("high_impact_task")
    blocked=bool(reasons) and not approved
    return {"allowed":not blocked,"requires_confirmation":blocked,"reasons":reasons,"policy_version":"3.0"}

def independent_verify(task,action,before,after):
    act=str(action.get("action","observe")); p=action.get("params") if isinstance(action.get("params"),dict) else {}; changed=before.strip()!=after.strip(); reasons=[]; ok=True
    if act in {"tap","long_press","swipe","back","open_url","open_app_by_name","click_any_text"} and not changed and act!="observe": ok=False; reasons.append("no_ui_change")
    if act=="click_any_text":
        texts=p.get("texts") or ([p.get("text")] if p.get("text") else [])
        if texts and any(str(t).lower() in after.lower() for t in texts): ok=False; reasons.append("target_still_visible")
    if act=="done" and not changed and before: reasons.append("no_post_change_evidence")
    return {"verified":ok,"changed":changed,"reasons":reasons,"verifier":"independent-rule-gate","verifier_version":"3.0"}

def fallback_step(req,obs):
    text = obs.get("screen_summary","") if isinstance(obs,dict) else str(obs)
    t=(text+" "+req.ui_tree).lower()
    for label in ["continue","التالي","متابعة","موافق","ok","تأكيد","submit","إرسال"]:
        if label in t:return {"action":"click_any_text","params":{"texts":[label]},"message":"اختيار زر ظاهر ثم التحقق","done":False,"wait_after_ms":700}
    return {"action":"observe","params":{},"message":"لا يوجد هدف مؤكد؛ إعادة الملاحظة","done":False,"wait_after_ms":500}

def submit(kind,fn):
    jid=uuid.uuid4().hex
    with JOB_LOCK:JOBS[jid]={"status":"pending","kind":kind}
    def run():
        with JOB_LOCK:JOBS[jid]["status"]="running"
        try:
            r=fn();
            with JOB_LOCK:JOBS[jid].update(status="completed",result=r)
        except Exception as e: JOBS[jid].update(status="failed",error=str(e))
    EXECUTOR.submit(run); return {"job_id":jid,"status":"pending"}

@app.get("/health")
def health():
    return {"ok":True,"brain_configured":bool(LOCAL_BASE and LOCAL_MODEL),"model":LOCAL_MODEL,"local_vision":VISION_ENABLED,"vision_model":VISION_MODEL,"reasoning_model":REASONING_MODEL,"reasoning_provider":"huggingface-router" if HF_TOKEN else "render-local-fallback","external_fallback_configured":bool(EXT_BASE and EXT_MODEL),"routing":True,"verifier":True,"state_persistence":True,"version":app.version}

@app.post("/v1/agent/sessions")
def create_session(req:SessionRequest,authorization:str|None=Header(default=None)):
    auth(authorization); sid=ensure_session(req.session_id,req.title); return {"session_id":sid,"state":load_state(sid)}
@app.get("/v1/agent/sessions/{sid}")
def get_session(sid:str,authorization:str|None=Header(default=None)):
    auth(authorization); return {"session_id":sid,"state":load_state(sid),"events":memory(sid,48)}
@app.post("/v1/agent/state")
def put_state(req:StateRequest,authorization:str|None=Header(default=None)):
    auth(authorization); save_state(req.session_id,req.state); remember(req.session_id,"state",req.state); return {"saved":True,"session_id":req.session_id}
@app.get("/v1/agent/state/{sid}")
def get_state(sid:str,authorization:str|None=Header(default=None)):
    auth(authorization); return {"session_id":sid,"state":load_state(sid)}
@app.post("/v1/agent/verify")
def verify(req:VerifyRequest,authorization:str|None=Header(default=None)):
    auth(authorization); v=safety(req.task,req.decision,req.approved_risks); remember(req.session_id,"safety_verification",v); return v
@app.post("/v1/agent/verify-result")
def verify_result(req:ResultVerifyRequest,authorization:str|None=Header(default=None)):
    auth(authorization); v=independent_verify(req.task,req.action,req.before_ui_tree,req.after_ui_tree); remember(req.session_id,"result_verification",v); return v
@app.post("/v1/agent/plan")
def plan(req:PlanRequest,authorization:str|None=Header(default=None)):
    auth(authorization); return submit("plan",lambda: run_plan(req))
def run_plan(req):
    sid=ensure_session(req.session_id); raw,p=reasoning(PLAN_SYSTEM,json.dumps({"task":req.task,"attachments":req.attachments[:8],"device":req.device,"memory":memory(sid,12)},ensure_ascii=False))
    try:
        x=extract_json(raw); steps=x.get("steps") if isinstance(x.get("steps"),list) else []
        if not steps: raise ValueError("missing steps")
        out={"summary":str(x.get("summary","خطة UCOA")),"steps":[str(s) for s in steps[:5]],"output_mode":"model","provider":p}
    except Exception as e:
        out={"summary":"خطة آمنة قابلة للتحقق","steps":["افتح الهدف المناسب.","نفذ الإجراء المطلوب.","تحقق من النتيجة."],"output_mode":"repair","provider":p,"error":str(e)}
    out["session_id"]=sid; remember(sid,"plan",out); save_state(sid,{"phase":"planned","task":req.task,"step":0,"plan":out}); return out
@app.get("/v1/agent/jobs/{jid}")
def get_job(jid:str,authorization:str|None=Header(default=None)):
    auth(authorization)
    with JOB_LOCK:x=dict(JOBS.get(jid,{}))
    if not x: raise HTTPException(404,"Unknown job")
    return x
@app.post("/v1/agent/step")
def step(req:StepRequest,authorization:str|None=Header(default=None)):
    auth(authorization); return submit("step",lambda: run_step(req))
def run_step(req):
    sid=ensure_session(req.session_id); obs={"screen_summary":"No screenshot","elements":[],"confidence":0.0}; vp=None
    if req.screenshot_base64 and VISION_ENABLED:
        try: obs,vp=call_vision(req.task,req.ui_tree,req.screenshot_base64); remember(sid,"visual_observation",obs)
        except Exception as e: remember(sid,"visual_error",{"error":str(e)})
    prompt=json.dumps({"task":req.task,"step":req.step,"history":req.history[-8:],"memory":memory(sid,16),"state":load_state(sid),"visual_observation":obs,"ui_tree":req.ui_tree[:14000],"installed_apps":req.installed_apps[:100],"capabilities":req.capabilities},ensure_ascii=False)
    try:
        raw,p=reasoning(STEP_SYSTEM,prompt); result=extract_json(raw); action=str(result.get("action","observe"));
        if action not in ACTIONS: raise ValueError("invalid action")
        result["action"]=action; result["params"]=result.get("params") if isinstance(result.get("params"),dict) else {}; result["done"]=bool(result.get("done",False)); result["wait_after_ms"]=max(150,min(5000,int(result.get("wait_after_ms",700)))); result["message"]=str(result.get("message","")); result["output_mode"]="model"
    except Exception as e:
        result=fallback_step(req,obs); p="repair"; result["error"]=str(e)
    result.update(provider=p,vision_provider=vp,visual_observation=obs,session_id=sid,verification=safety(req.task,result,req.approved_risks))
    remember(sid,"decision",result); save_state(sid,{"phase":"executing","task":req.task,"step":req.step,"last_decision":result}); return result
