"""Live provider router for UCOA.

Secrets stay in server environment variables. The router prefers OmniRoute,
then uses direct providers for resilience. Screenshot tasks prefer multimodal
providers; text-only planning prefers the fast reasoning providers.
"""
from __future__ import annotations
import base64,json,os,re,time
from typing import Any
from urllib.error import HTTPError,URLError
from urllib.parse import quote
from urllib.request import Request,urlopen

TIMEOUT=int(os.getenv("UCOA_PROVIDER_TIMEOUT","12")); MAX_TOKENS=int(os.getenv("UCOA_PROVIDER_MAX_TOKENS","256"))
PROVIDERS=[
 {"name":"omniroute","key_env":"UCOA_OMNIROUTE_API_KEY","base_env":"UCOA_OMNIROUTE_BASE_URL","model_env":"UCOA_OMNIROUTE_MODEL","default_base":"","default_model":"auto","vision":True},
 {"name":"gemini","key_env":"UCOA_GEMINI_API_KEY","base_env":None,"model_env":"UCOA_GEMINI_MODEL","default_base":"https://generativelanguage.googleapis.com/v1beta/openai","default_model":"gemini-3.8-flash","vision":True},
 {"name":"deepseek","key_env":"UCOA_DEEPSEEK_API_KEY","base_env":None,"model_env":"UCOA_DEEPSEEK_MODEL","default_base":"https://api.deepseek.com/v1","default_model":"deepseek-v4-flash-vision-exp","vision":True},
 {"name":"cerebras","key_env":"UCOA_CEREBRAS_API_KEY","base_env":None,"model_env":"UCOA_CEREBRAS_MODEL","default_base":"https://api.cerebras.ai/v1","default_model":"gpt-oss-120b","vision":False},
 {"name":"groq","key_env":"UCOA_GROQ_API_KEY","base_env":None,"model_env":"UCOA_GROQ_MODEL","default_base":"https://api.groq.com/openai/v1","default_model":"openai/gpt-oss-120b","vision":False},
]

def _cfg(p:dict[str,Any])->tuple[str,str,str,bool]:
 key=os.getenv(p["key_env"],"").strip()
 if not key: raise RuntimeError("provider not configured")
 base=(os.getenv(p["base_env"],"") if p["base_env"] else p["default_base"]).rstrip("/")
 model=os.getenv(p["model_env"],p["default_model"]).strip()
 if not base or not model: raise RuntimeError("provider endpoint/model not configured")
 return base,key,model,bool(p["vision"])

def _native_gemini(model:str,key:str,system:str,user:str,image:str,timeout:int)->str:
 url=f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model,safe='')}:generateContent?key={quote(key,safe='')}"
 payload={"systemInstruction":{"parts":[{"text":system}]},"contents":[{"role":"user","parts":[{"text":user},{"inlineData":{"mimeType":"image/jpeg","data":image}}]}],"generationConfig":{"temperature":0,"maxOutputTokens":MAX_TOKENS}}
 req=Request(url,data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),headers={"Content-Type":"application/json"},method="POST")
 try:
  with urlopen(req,timeout=timeout) as resp: body=json.loads(resp.read().decode("utf-8"))
 except HTTPError as exc:
  detail=""
  try: detail=exc.read().decode("utf-8","replace")[:300]
  except Exception: pass
  raise RuntimeError(f"HTTP_{exc.code}:{detail}") from exc
 except (URLError,TimeoutError) as exc:
  raise RuntimeError(type(exc).__name__) from exc
 parts=[]
 for cand in body.get("candidates") or []:
  for part in (cand.get("content") or {}).get("parts") or []:
   if isinstance(part,dict) and part.get("text"): parts.append(str(part["text"]))
 text="\n".join(parts).strip()
 if not text: raise RuntimeError("no Gemini content")
 return text

def _chat(base:str,key:str,model:str,system:str,user:str,image:str|None,timeout:int)->str:
 if image and "generativelanguage.googleapis.com" in base: return _native_gemini(model,key,system,user,image,timeout)
 content:Any=user
 if image: content=[{"type":"text","text":user},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{image}"}}]
 payload={"model":model,"temperature":0,"max_tokens":MAX_TOKENS,"messages":[{"role":"system","content":system},{"role":"user","content":content}]}
 url=base if base.endswith("/chat/completions") else base+"/chat/completions"
 req=Request(url,data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),headers={"Content-Type":"application/json","Authorization":f"Bearer {key}"},method="POST")
 try:
  with urlopen(req,timeout=timeout) as resp: body=json.loads(resp.read().decode("utf-8"))
 except HTTPError as exc:
  raise RuntimeError(f"HTTP_{exc.code}") from exc
 except (URLError,TimeoutError) as exc: raise RuntimeError(type(exc).__name__) from exc
 choices=body.get("choices") or []
 if not choices: raise RuntimeError("no choices")
 content=(choices[0].get("message") or {}).get("content","")
 if isinstance(content,list): content="".join(str(x.get("text","")) for x in content if isinstance(x,dict))
 return str(content)

def _order(image:str|None)->list[str]:
 configured=[]
 for p in PROVIDERS:
  try:_cfg(p); configured.append(p["name"])
  except Exception:pass
 if image:return [n for n in ["omniroute","gemini","deepseek","cerebras","groq"] if n in configured]
 return [n for n in ["omniroute","cerebras","groq","gemini","deepseek"] if n in configured]

def _get(name:str): return next(p for p in PROVIDERS if p["name"]==name)

def call(system:str,user:str,image:str|None=None)->tuple[str,str]:
 errors=[]
 for name in _order(image):
  try:
   p=_get(name); base,key,model,vision=_cfg(p); raw=_chat(base,key,model,system,user,image if vision else None,TIMEOUT)
   if raw.strip(): return raw,name
  except Exception as exc: errors.append(f"{name}:{str(exc)[:120]}")
 raise RuntimeError("all providers failed; "+",".join(errors))

def _extract_json(raw:str)->dict[str,Any]:
 t=re.sub(r"^```(?:json)?\s*|\s*```$","",raw.strip())
 try:
  value=json.loads(t)
  if isinstance(value,dict): return value
 except json.JSONDecodeError: pass
 m=re.search(r"\{.*\}",t,re.S)
 if m:
  value=json.loads(m.group(0))
  if isinstance(value,dict): return value
 raise ValueError("provider returned non-JSON output")

def reasoning(system:str,user:str)->tuple[str,str]: return call(system,user,None)

def visual(task:str,ui_tree:str,image:str)->tuple[dict[str,Any],str]:
 system=("You are UCOA visual perception. Inspect only the screenshot and UI tree. Do not choose an action. "
         "Return ONLY JSON: {\"screen_summary\":string,\"elements\":[{\"text\":string,\"role\":string,\"x\":number,\"y\":number}],\"visible_goal_state\":string,\"confidence\":number}. Never invent unseen elements.")
 raw,provider=call(system,json.dumps({"task":task,"ui_tree":ui_tree[:18000]},ensure_ascii=False),image)
 return _extract_json(raw),provider

def probe()->dict[str,Any]:
 system="Return only JSON."; prompt='Return exactly {"ok":true,"kind":"probe"}'; results=[]
 for p in PROVIDERS:
  name=p["name"]; started=time.perf_counter()
  try:
   base,key,model,vision=_cfg(p); raw=_chat(base,key,model,system,prompt,None,min(TIMEOUT,8))
   results.append({"provider":name,"model":model,"vision":vision,"ok":bool(raw.strip()),"latency_s":round(time.perf_counter()-started,3)})
  except Exception as exc:
   results.append({"provider":name,"model":p.get("model_env"),"vision":p["vision"],"ok":False,"latency_s":round(time.perf_counter()-started,3),"error":str(exc)[:160]})
 usable=[r for r in results if r.get("ok")]
 return {"ok":bool(usable),"best":min(usable,key=lambda r:r.get("latency_s",9999),default=None),"providers":results}

def safe_text_probe()->dict[str,Any]: return probe()
