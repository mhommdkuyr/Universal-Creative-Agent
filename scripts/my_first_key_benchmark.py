#!/usr/bin/env python3
import argparse, base64, json, os, time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

TIMEOUT=20
KEY=os.environ.get("PROVIDER_KEY","").strip()
if not KEY:
    raise SystemExit("PROVIDER_KEY is required")

def req(url, headers=None, method="GET", body=None):
    h={"Accept":"application/json","User-Agent":"ucoa-provider-benchmark/1"}
    if headers: h.update(headers)
    r=Request(url,headers=h,method=method,data=body)
    with urlopen(r,timeout=TIMEOUT) as x:
        return json.loads(x.read().decode("utf-8"))

def auth_get(url, kind="bearer"):
    if kind=="gemini":
        return req(url, {"x-goog-api-key":KEY})
    return req(url, {"Authorization":f"Bearer {KEY}"})

candidates=[
    ("openrouter","https://openrouter.ai/api/v1/models","bearer"),
    ("openai","https://api.openai.com/v1/models","bearer"),
    ("groq","https://api.groq.com/openai/v1/models","bearer"),
    ("together","https://api.together.xyz/v1/models","bearer"),
    ("cerebras","https://api.cerebras.ai/v1/models","bearer"),
    ("deepseek","https://api.deepseek.com/models","bearer"),
    ("mistral","https://api.mistral.ai/v1/models","bearer"),
    ("novita","https://api.novita.ai/openai/models","bearer"),
    ("gemini","https://generativelanguage.googleapis.com/v1beta/models","gemini"),
]

detected=[]
for name,url,kind in candidates:
    try:
        started=time.perf_counter()
        data=auth_get(url,kind)
        detected.append({"provider":name,"url":url,"latency_ms":round((time.perf_counter()-started)*1000,2),"ok":True,"payload":data})
    except Exception as e:
        detected.append({"provider":name,"url":url,"ok":False,"error":str(e)[:200]})

best=next((x for x in detected if x["ok"]),None)
out={"detected":detected,"selected":best["provider"] if best else None}
if best:
    payload=best["payload"]
    models=payload.get("data") if isinstance(payload,dict) else None
    if models is None and isinstance(payload,dict):
        models=payload.get("models")
    if not isinstance(models,list): models=[]
    out["models"]=[]
    for m in models:
        if not isinstance(m,dict): continue
        entry={"id":m.get("id") or m.get("name"),"pricing":m.get("pricing"),"architecture":m.get("architecture"),"input_modalities":m.get("architecture",{}).get("input_modalities") if isinstance(m.get("architecture"),dict) else None}
        out["models"].append(entry)

with open(os.environ.get("OUT","provider-discovery.json"),"w",encoding="utf-8") as f:
    json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps({"selected":out["selected"],"model_count":len(out["models"])},ensure_ascii=False))

# trigger provider discovery on next push
