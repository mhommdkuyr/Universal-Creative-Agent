#!/usr/bin/env python3
import argparse, base64, json, os, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from PIL import Image, ImageDraw

KEY=os.environ.get('PROVIDER_KEY','').strip()
TIMEOUT=20
TASKS=[
 {'name':'continue_button','instruction':'Identify the visible button labeled CONTINUE. Return JSON with screen_summary, elements, visible_goal_state, confidence.','target':'CONTINUE'},
 {'name':'wifi_target','instruction':'Identify the visible Wi-Fi item on the Android Settings-style screen. Return JSON with screen_summary, elements, visible_goal_state, confidence.','target':'Wi-Fi'},
]

def make_image(kind):
 img=Image.new('RGB',(520,260),'white'); d=ImageDraw.Draw(img)
 if kind=='continue':
  d.text((30,25),'UCOA Test Screen',fill='black')
  d.rounded_rectangle((80,100,260,170),radius=12,fill='#dddddd',outline='black'); d.text((135,125),'CONTINUE',fill='black')
  d.rounded_rectangle((285,100,440,170),radius=12,fill='#eeeeee',outline='black'); d.text((335,125),'Cancel',fill='black')
 else:
  d.text((30,20),'Settings',fill='black'); d.text((30,75),'Network & internet',fill='black')
  d.rounded_rectangle((25,105,240,155),radius=8,fill='#f0f0f0',outline='black'); d.text((45,122),'Wi-Fi',fill='black')
  d.text((25,185),'Bluetooth',fill='black'); d.text((250,122),'Connected',fill='black')
 p=Path('/tmp/'+kind+'.jpg'); img.save(p,'JPEG',quality=85); return base64.b64encode(p.read_bytes()).decode()
IMAGES={t['name']:make_image('continue' if t['name']=='continue_button' else 'wifi') for t in TASKS}

def call(protocol,chat_url,model,messages,image=None):
 headers={'Authorization':'Bearer '+KEY,'Content-Type':'application/json','Accept':'application/json'}
 if protocol=='cheaperinference':
  headers.pop('Authorization',None); headers['x-api-key']=KEY
 started=time.perf_counter()
 if protocol=='gemini':
  parts=[{'text':messages[-1].get('content','') if isinstance(messages[-1].get('content',''),str) else json.dumps(messages[-1].get('content'))}]
  if image: parts.append({'inline_data':{'mime_type':'image/jpeg','data':image}})
  body={'systemInstruction':{'parts':[{'text':messages[0].get('content','')}]},'contents':[{'role':'user','parts':parts}],'generationConfig':{'temperature':0,'maxOutputTokens':256}}
  headers={'x-goog-api-key':KEY,'Content-Type':'application/json','Accept':'application/json'}
  url=chat_url.format(model=model)
 else:
  content=messages[-1].get('content','')
  if image: content=[{'type':'text','text':content},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+image}}]
  body={'model':model,'messages':[{'role':'system','content':messages[0].get('content','')},{'role':'user','content':content}],'temperature':0,'max_tokens':256}
  if protocol=='cheaperinference': body['ranking']='speed'
  url=chat_url
 req=Request(url,data=json.dumps(body,ensure_ascii=False).encode(),headers=headers,method='POST')
 try:
  with urlopen(req,timeout=TIMEOUT) as r:
   response_headers=dict(r.headers.items()); data=json.loads(r.read().decode())
 except HTTPError as e:
  raise RuntimeError('HTTP '+str(e.code)+': '+e.read().decode('utf-8','replace')[:250])
 elapsed=round((time.perf_counter()-started)*1000,2)
 usage=data.get('usage') or data.get('usageMetadata') or {}
 if protocol=='gemini':
  text=''.join(str(p.get('text','')) for p in (data.get('candidates') or [{}])[0].get('content',{}).get('parts',[]) if isinstance(p,dict))
 else:
  text=(data.get('choices') or [{}])[0].get('message',{}).get('content','')
  if isinstance(text,list): text=''.join(str(x.get('text','') if isinstance(x,dict) else x) for x in text)
 if protocol=='cheaperinference':
  ci=data.get('cheaper_inference') or {}
  usage=dict(usage or {})
  usage['_billed_cost_usd']=ci.get('billed_cost_usd')
  usage['_routing_overhead_ms']=response_headers.get('x-ci-routing-overhead-ms')
  usage['_model_response_ms']=response_headers.get('x-ci-model-response-ms')
  usage['_tokens_saved']=response_headers.get('x-ci-tokens-saved')
  usage['_saved_usd']=response_headers.get('x-ci-saved-usd')
 return str(text),usage,elapsed

def parse_json(text):
 s=text.strip()
 if s.startswith('```'):
  p=s.split('\n',1); s=p[1] if len(p)==2 else s; s=s.rsplit('```',1)[0]
 try:return json.loads(s)
 except Exception:return None

def model_lists(catalog,selected):
 rows=catalog.get('models',[]) if isinstance(catalog,dict) else []
 ids={m.get('id') for m in rows if m.get('id')}
 if selected=='cheaperinference':
  vision_candidates=['gemini-3.7-flash','gemini-3.6-flash','gemini-3-5-flash','gemini-2.5-flash','google/gemini-3.5-flash-lite']
  decision_candidates=['gpt-6-astra','gpt-5.6-luna','gpt-5.6-sol','gpt-5.5','gpt-5.4-mini']
  vision=[m for m in vision_candidates if m in ids]
  decision=[m for m in decision_candidates if m in ids]
  return vision[:4],decision[:4]
 vision=[m.get('id') for m in rows if 'image' in ((m.get('input_modalities') or []))][:4]
 decision=[m.get('id') for m in rows if m.get('id')][:4]
 return vision,decision

def usage_counts(u):
 i=u.get('prompt_tokens',u.get('promptTokenCount',u.get('inputTokenCount')))
 o=u.get('completion_tokens',u.get('candidatesTokenCount',u.get('outputTokenCount')))
 t=u.get('total_tokens',u.get('totalTokenCount'))
 return i,o,t

def cost(model,usage,pricing):
 p=pricing.get(model) or {}
 i,o=usage_counts(usage)[:2]
 billed=usage.get('_billed_cost_usd') if isinstance(usage,dict) else None
 if billed is not None:
  try:return float(billed)
  except Exception: pass
 if i is None or o is None: return None
 try:return (float(i)*float(p.get('prompt',0))+float(o)*float(p.get('completion',0)))/1000000.0
 except Exception:return None

def has_target(obj,target): return target.lower() in json.dumps(obj,ensure_ascii=False).lower()

def main(out_file,catalog_file):
 discovery=json.loads(Path(catalog_file).read_text(encoding='utf-8'))
 selected=discovery.get('selected'); protocol=discovery.get('selected_protocol'); chat_url=discovery.get('selected_chat')
 rows={m.get('id'):m for m in discovery.get('models',[]) if m.get('id')}
 if not selected or not protocol or not chat_url: raise RuntimeError('MY_FIRST_KEY did not authenticate to any supported provider')
 vision,decision=model_lists(discovery,selected)
 pricing={k:(v.get('pricing') or {}) for k,v in rows.items()}
 results=[]
 for task in TASKS:
  for vm in vision:
   try:
    txt,vu,vl=call(protocol,chat_url,vm,[{'role':'system','content':'You are UCOA visual perception. Inspect only the screenshot. Return JSON with screen_summary, elements, visible_goal_state, confidence.'},{'role':'user','content':task['instruction']}],IMAGES[task['name']])
    vobj=parse_json(txt) or {'raw':txt[:1500]}; vok=has_target(vobj,task['target'])
   except Exception as e:
    for dm in decision: results.append({'task':task['name'],'vision_model':vm,'decision_model':dm,'pair_ok':False,'vision_ok':False,'decision_ok':False,'error':'VISION:'+str(e)[:300]})
    continue
   for dm in decision:
    try:
     payload=json.dumps({'task':task['instruction'],'visual_observation':vobj,'target':task['target']},ensure_ascii=False)
     dt,du,dl=call(protocol,chat_url,dm,[{'role':'system','content':'You are UCOA Android controller. Return ONLY JSON with action, params, verification_goal, confidence. For a visible textual target, use action click_any_text with params texts containing the exact target.'},{'role':'user','content':payload}])
     dobj=parse_json(dt) or {'raw':dt[:1500]}; action=str(dobj.get('action','')).lower() if isinstance(dobj,dict) else ''
     params=dobj.get('params',{}) if isinstance(dobj,dict) else {}; texts=params.get('texts',[]) if isinstance(params,dict) else []; texts=[texts] if isinstance(texts,str) else texts
     dok=action=='click_any_text' and any(str(x).strip().lower()==task['target'].lower() for x in texts)
     vc=cost(vm,vu,pricing); dc=cost(dm,du,pricing)
     results.append({'task':task['name'],'vision_model':vm,'decision_model':dm,'vision_ok':vok,'decision_ok':dok,'pair_ok':vok and dok,'vision_latency_ms':vl,'decision_latency_ms':dl,'total_latency_ms':round(vl+dl,2),'vision_usage':vu,'decision_usage':du,'vision_cost_usd':vc,'decision_cost_usd':dc,'pair_cost_usd':(vc or 0)+(dc or 0),'vision_routing_ms':vu.get('_routing_overhead_ms'),'vision_model_response_ms':vu.get('_model_response_ms'),'decision_routing_ms':du.get('_routing_overhead_ms'),'decision_model_response_ms':du.get('_model_response_ms'),'vision_billed_cost_usd':vu.get('_billed_cost_usd'),'decision_billed_cost_usd':du.get('_billed_cost_usd'),'vision_text':txt[:1000],'decision_text':dt[:1000]})
    except Exception as e: results.append({'task':task['name'],'vision_model':vm,'decision_model':dm,'vision_ok':vok,'decision_ok':False,'pair_ok':False,'error':'DECISION:'+str(e)[:300]})
 summary={}
 for r in results:
  k=r['vision_model']+' + '+r['decision_model']; q=summary.setdefault(k,{'vision_model':r['vision_model'],'decision_model':r['decision_model'],'tasks':0,'successes':0,'latencies':[],'costs':[],'errors':0}); q['tasks']+=1
  if r.get('pair_ok'): q['successes']+=1
  if r.get('total_latency_ms') is not None: q['latencies'].append(r['total_latency_ms'])
  if r.get('pair_cost_usd') is not None: q['costs'].append(r['pair_cost_usd'])
  if r.get('error'): q['errors']+=1
 pairs=[]
 for q in summary.values(): q['accuracy']=q['successes']/q['tasks'] if q['tasks'] else 0; q['avg_latency_ms']=sum(q['latencies'])/len(q['latencies']) if q['latencies'] else None; q['avg_cost_usd']=sum(q['costs'])/len(q['costs']) if q['costs'] else None; pairs.append(q)
 pairs.sort(key=lambda x:(-x['accuracy'],x['avg_latency_ms'] if x['avg_latency_ms'] is not None else 1e99,x['avg_cost_usd'] if x['avg_cost_usd'] is not None else 1e99))
 Path(out_file).write_text(json.dumps({'selected_provider':selected,'protocol':protocol,'vision_models':vision,'decision_models':decision,'tasks':TASKS,'pairs':pairs,'raw_results':results},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'selected_provider':selected,'pairs':len(pairs),'raw_results':len(results)},ensure_ascii=False))

if __name__=='__main__':
 ap=argparse.ArgumentParser(); ap.add_argument('--out',default='provider-benchmark.json'); ap.add_argument('--catalog',default='provider-discovery.json'); args=ap.parse_args(); main(args.out,args.catalog)