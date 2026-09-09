"""Production provider router for UCOA."""
from __future__ import annotations
import hashlib, json, os, re, time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from observability import span, set_measurement
CONNECT_TIMEOUT=float(os.getenv("UCOA_PROVIDER_CONNECT_TIMEOUT","2")); TEXT_TIMEOUT=float(os.getenv("UCOA_PROVIDER_TEXT_TIMEOUT","12")); VISION_TIMEOUT=float(os.getenv("UCOA_PROVIDER_VISION_TIMEOUT","20")); MAX_TOKENS=int(os.getenv("UCOA_PROVIDER_MAX_TOKENS","256")); CACHE_TTL=max(0.0,float(os.getenv("UCOA_VISION_CACHE_TTL","3"))); CB_FAILURES=max(1,int(os.getenv("UCOA_PROVIDER_CB_FAILURES","3"))); CB_COOLDOWN=max(1.0,float(os.getenv("UCOA_PROVIDER_CB_COOLDOWN","30")))
PROVIDERS=[
 {"name":"gemini","key_env":"UCOA_GEMINI_API_KEY","base_env":"UCOA_GEMINI_BASE_URL","model_env":"UCOA_GEMINI_MODEL","default_base":"https://generativelanguage.googleapis.com/v1beta/openai","default_model":"gemini-2.5-flash","vision":True},
 {"name":"huggingface-text","key_env":"HF_TOKEN","base_env":"HF_BASE_URL","model_env":"HF_MODEL","default_base":"https://router.huggingface.co/v1","default_model":"Qwen/Qwen3-4B-Instruct-2507:fastest","vision":False},
 {"name":"huggingface-vision","key_env":"HF_TOKEN","base_env":"HF_BASE_URL","model_env":"HF_VISION_MODEL","default_base":"https://router.huggingface.co/v1","default_model":"Qwen/Qwen3-VL-2B-Instruct:fastest","vision":True},
 {"name":"deepseek","key_env":"UCOA_DEEPSEEK_API_KEY","base_env":"UCOA_DEEPSEEK_BASE_URL","model_env":"UCOA_DEEPSEEK_MODEL","default_base":"https://api.deepseek.com","default_model":"deepseek-chat","vision":False},
 {"name":"omniroute","key_env":"UCOA_OMNIROUTE_API_KEY","base_env":"UCOA_OMNIROUTE_BASE_URL","model_env":"UCOA_OMNIROUTE_MODEL","default_base":"","default_model":"auto","vision":True},
 {"name":"cerebras","key_env":"UCOA_CEREBRAS_API_KEY","base_env":"UCOA_CEREBRAS_BASE_URL","model_env":"UCOA_CEREBRAS_MODEL","default_base":"https://api.cerebras.ai/v1","default_model":"gpt-oss-120b","vision":False},
 {"name":"groq","key_env":"UCOA_GROQ_API_KEY","base_env":"UCOA_GROQ_BASE_URL","model_env":"UCOA_GROQ_MODEL","default_base":"https://api.groq.com/openai/v1","default_model":"openai/gpt-oss-120b","vision":False},]
@dataclass
class CircuitState: failures:int=0; opened_at:float=0.0
_BREAKERS={p["name"]:CircuitState() for p in PROVIDERS}; _VISION_CACHE={}
def _cfg(p):
 key=os.getenv(p["key_env"],"").strip()
 if not key: raise RuntimeError("provider not configured")
 base=(os.getenv(p["base_env"],"").strip() or p["default_base"]).rstrip("/"); model=os.getenv(p["model_env"],p["default_model"]).strip()
 if not base or not model: raise RuntimeError("provider endpoint/model not configured")
 return base,key,model,bool(p["vision"])
def _provider(name): return next(p for p in PROVIDERS if p["name"]==name)
def _is_open(name):
 s=_BREAKERS[name]
 if not s.opened_at:return False
 if time.monotonic()-s.opened_at>=CB_COOLDOWN:s.failures=0;s.opened_at=0.0;return False
 return True
def _success(name):_BREAKERS[name]=CircuitState()
def _failure(name):
 s=_BREAKERS[name];s.failures+=1
 if s.failures>=CB_FAILURES:s.opened_at=time.monotonic()
def _chat(base,key,model,system,user,image,timeout):
 content=user if not image else [{"type":"text","text":user},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{image}","detail":"high"}}]
 payload={"model":model,"temperature":0,"max_tokens":MAX_TOKENS,"messages":[{"role":"system","content":system},{"role":"user","content":content}]};url=base if base.endswith("/chat/completions") else base+"/chat/completions";req=Request(url,data=json.dumps(payload,ensure_ascii=False).encode(),headers={"Content-Type":"application/json","Accept":"application/json","Authorization":f"Bearer {key}"},method="POST")
 with urlopen(req,timeout=timeout) as resp:body=json.loads(resp.read().decode())
 choices=body.get("choices") or []
 if not choices:raise RuntimeError("no choices")
 content=(choices[0].get("message") or {}).get("content","")
 if isinstance(content,list):content="".join(str(x.get("text","") if isinstance(x,dict) else x) for x in content)
 text=str(content).strip()
 if not text:raise RuntimeError("empty response")
 return text
def _ordered(image):
 configured=[]
 for p in PROVIDERS:
  try:_cfg(p);configured.append(p["name"])
  except Exception:pass
 preferred=["gemini","huggingface-vision","deepseek","omniroute","huggingface-text"] if image else ["gemini","huggingface-text","cerebras","groq","deepseek","omniroute"]
 return [n for n in preferred if n in configured and not _is_open(n)]
def call(system,user,image=None):
 errors=[];timeout=VISION_TIMEOUT if image else TEXT_TIMEOUT
 for name in _ordered(image):
  started=time.perf_counter()
  try:
   p=_provider(name);base,key,model,supports=_cfg(p)
   if image and not supports:raise RuntimeError("provider does not support vision")
   with span("ai.provider",f"{name} inference",provider=name,model=model,multimodal=bool(image)):raw=_chat(base,key,model,system,user,image,timeout)
   _success(name);set_measurement(f"provider.{name}.latency_ms",(time.perf_counter()-started)*1000);return raw,name
  except HTTPError as e:_failure(name);errors.append(f"{name}:HTTP_{e.code}")
  except (URLError,TimeoutError) as e:_failure(name);errors.append(f"{name}:{type(e).__name__}")
  except Exception as e:_failure(name);errors.append(f"{name}:{str(e)[:120]}")
 raise RuntimeError("all providers failed; "+",".join(errors) if errors else "no provider configured")
def _extract_json(raw):
 text=re.sub(r"^```(?:json)?\s*|\s*```$","",raw.strip())
 try:
  value=json.loads(text)
  if isinstance(value,dict):return value
 except json.JSONDecodeError:pass
 match=re.search(r"\{.*\}",text,re.S)
 if match:
  value=json.loads(match.group(0))
  if isinstance(value,dict):return value
 raise ValueError("provider returned non-JSON output")
def reasoning(system,user):return call(system,user,None)
def visual(task,ui_tree,image):
 key=hashlib.sha256(image.encode("ascii","ignore")).hexdigest();now=time.monotonic();cached=_VISION_CACHE.get(key)
 if cached and now-cached[0]<=CACHE_TTL:return cached[1],cached[2]
 system='You are UCOA visual perception. Inspect only the current Android screenshot and UI tree. Return ONLY valid JSON: {"screen_summary":string,"elements":[{"text":string,"role":string,"x":number,"y":number}],"visible_goal_state":string,"confidence":number}. Never invent unseen elements. Coordinates normalized 0..1000.'
 raw,provider=call(system,json.dumps({"task":task,"ui_tree":ui_tree[:18000]},ensure_ascii=False),image);value=_extract_json(raw);_VISION_CACHE[key]=(now,value,provider);return value,provider
def safe_text_probe():
 configured=[p["name"] for p in PROVIDERS if os.getenv(p["key_env"],"").strip()]
 if not configured:return {"ok":False,"configured":False,"providers":[]}
 try:
  raw,provider=call("Return ONLY JSON.","Return exactly {\"ok\":true}.");return {"ok":True,"configured":True,"providers":[{"provider":provider,"ok":True}],"response":_extract_json(raw)}
 except Exception as exc:return {"ok":False,"configured":True,"providers":[],"error":type(exc).__name__}
