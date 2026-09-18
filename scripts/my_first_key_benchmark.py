#!/usr/bin/env python3
import argparse, json, os, time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

TIMEOUT=20
KEY=os.environ.get('PROVIDER_KEY','').strip()
if not KEY: raise SystemExit('PROVIDER_KEY is required')

def request_json(url, headers=None, method='GET', body=None):
    h={'Accept':'application/json','User-Agent':'ucoa-provider-discovery/2'}
    if headers: h.update(headers)
    req=Request(url,headers=h,method=method,data=body)
    started=time.perf_counter()
    try:
        with urlopen(req,timeout=TIMEOUT) as resp:
            data=json.loads(resp.read().decode('utf-8'))
            return resp.status,data,round((time.perf_counter()-started)*1000,2)
    except HTTPError as e:
        body=e.read().decode('utf-8','replace')[:500]
        return e.code,{'error':body},round((time.perf_counter()-started)*1000,2)
    except Exception as e:
        return None,{'error':str(e)[:500]},round((time.perf_counter()-started)*1000,2)

providers=[
  {'name':'openrouter','models':'https://openrouter.ai/api/v1/models','chat':'https://openrouter.ai/api/v1/chat/completions','protocol':'openai'},
  {'name':'openai','models':'https://api.openai.com/v1/models','chat':'https://api.openai.com/v1/chat/completions','protocol':'openai'},
  {'name':'groq','models':'https://api.groq.com/openai/v1/models','chat':'https://api.groq.com/openai/v1/chat/completions','protocol':'openai'},
  {'name':'together','models':'https://api.together.xyz/v1/models','chat':'https://api.together.xyz/v1/chat/completions','protocol':'openai'},
  {'name':'cerebras','models':'https://api.cerebras.ai/v1/models','chat':'https://api.cerebras.ai/v1/chat/completions','protocol':'openai'},
  {'name':'deepseek','models':'https://api.deepseek.com/models','chat':'https://api.deepseek.com/chat/completions','protocol':'openai'},
  {'name':'mistral','models':'https://api.mistral.ai/v1/models','chat':'https://api.mistral.ai/v1/chat/completions','protocol':'openai'},
  {'name':'novita','models':'https://api.novita.ai/openai/models','chat':'https://api.novita.ai/openai/chat/completions','protocol':'openai'},
  {'name':'fireworks','models':'https://api.fireworks.ai/inference/v1/models','chat':'https://api.fireworks.ai/inference/v1/chat/completions','protocol':'openai'},
  {'name':'sambanova','models':'https://api.sambanova.ai/v1/models','chat':'https://api.sambanova.ai/v1/chat/completions','protocol':'openai'},
  {'name':'gemini','models':'https://generativelanguage.googleapis.com/v1beta/models','chat':'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent','protocol':'gemini'},
  {'name':'cheaperinference','models':'https://api.cheaperinference.com/v1/models','chat':'https://api.cheaperinference.com/v1/chat/completions','protocol':'cheaperinference'},
]

def auth_headers(protocol):
    if protocol=='gemini': return {'x-goog-api-key':KEY}
    if protocol=='cheaperinference': return {'x-api-key':KEY}
    return {'Authorization':'Bearer '+KEY}

def models_from(payload):
    if not isinstance(payload,dict): return []
    rows=payload.get('data') or payload.get('models') or []
    out=[]
    for m in rows:
        if not isinstance(m,dict): continue
        mid=m.get('id') or m.get('name','').split('/')[-1]
        arch=m.get('architecture') or {}
        out.append({'id':mid,'pricing':m.get('pricing'),'architecture':arch,'input_modalities':arch.get('input_modalities') if isinstance(arch,dict) else None})
    return out

def choose_model(rows, want_image=False):
    candidates=[]
    for m in rows:
        mid=m.get('id')
        if not mid: continue
        mods=m.get('input_modalities') or []
        p=m.get('pricing') or {}
        free=str(p.get('prompt',''))=='0' and str(p.get('completion',''))=='0'
        if want_image and 'image' not in mods: continue
        candidates.append((0 if free else 1, mid))
    if not candidates and want_image: return None
    if not candidates: return rows[0].get('id') if rows else None
    candidates.sort(key=lambda x:(x[0],x[1]))
    return candidates[0][1]

def smoke(provider, model):
    if not model: return False,{'error':'no model'},None
    h=auth_headers(provider['protocol']); body=None
    if provider['protocol']=='gemini':
        url=provider['chat'].format(model=model)
        body=json.dumps({'contents':[{'parts':[{'text':'Return exactly OK.'}]}],'generationConfig':{'temperature':0,'maxOutputTokens':4}}).encode()
        h['Content-Type']='application/json'
    else:
        url=provider['chat']
        body=json.dumps({'model':model,'messages':[{'role':'user','content':'Return exactly OK.'}],'temperature':0,'max_tokens':4}).encode()
        h['Content-Type']='application/json'
    code,data,lat=request_json(url,h,'POST',body)
    ok=code==200
    return ok,{'http_status':code,'latency_ms':lat,'error':data.get('error') if isinstance(data,dict) else None},data

detected=[]
for provider in providers:
    code,payload,lat=request_json(provider['models'],auth_headers(provider['protocol']))
    rows=models_from(payload) if code==200 else []
    smoke_model=choose_model(rows,False)
    ok,probe,probe_body=smoke(provider,smoke_model) if code==200 else (False,{'http_status':code,'latency_ms':lat,'error':payload.get('error') if isinstance(payload,dict) else None},None)
    detected.append({'provider':provider['name'],'protocol':provider['protocol'],'models_url':provider['models'],'chat_url':provider['chat'],'models_http_status':code,'models_latency_ms':lat,'authenticated':ok,'smoke_model':smoke_model,'smoke':probe,'models':rows})

selected=next((x for x in detected if x['authenticated']),None)
out={'selected':selected['provider'] if selected else None,'selected_protocol':selected['protocol'] if selected else None,'selected_chat':selected['chat_url'] if selected else None,'detected':detected,'models':(selected['models'] if selected else [])}
with open(os.environ.get('OUT','provider-discovery.json'),'w',encoding='utf-8') as f: json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps({'selected':out['selected'],'selected_protocol':out['selected_protocol'],'model_count':len(out['models'])},ensure_ascii=False))