#!/usr/bin/env python3
import argparse, base64, json, os, time
from pathlib import Path
from urllib.request import Request, urlopen
from PIL import Image, ImageDraw

BASE='https://openrouter.ai/api/v1/chat/completions'
KEY=os.environ['PROVIDER_KEY']

VISION_MODELS=['google/gemini-3.8-flash','inclusionai/ling-3.0-flash-vl:free','nex-agi/nex-n2.5-pro:free','qwen/qwen3.8-27b:free']
DECISION_MODELS=['openai/gpt-6-astra','qwen/qwen3.8-27b:free','nex-agi/nex-n2.5-pro:free','inclusionai/ling-3.0-flash-sante:free']
TASKS=[
  {'name':'continue_button','instruction':'Identify the visible button labeled CONTINUE. Return JSON with the visible_goal_state, elements, confidence.','target':'CONTINUE'},
  {'name':'wifi_target','instruction':'Identify the visible Wi-Fi item on the Settings-style screen. Return JSON with the visible_goal_state, elements, confidence.','target':'Wi-Fi'},
]

def make_image(kind):
    img=Image.new('RGB',(520,260),'white'); d=ImageDraw.Draw(img)
    if kind=='continue':
        d.text((30,25),'UCOA Test Screen',fill='black')
        d.rounded_rectangle((80,100,260,170),radius=12,fill='#dddddd',outline='black')
        d.text((135,125),'CONTINUE',fill='black')
        d.rounded_rectangle((285,100,440,170),radius=12,fill='#eeeeee',outline='black')
        d.text((335,125),'Cancel',fill='black')
    else:
        d.text((30,20),'Settings',fill='black')
        d.text((30,75),'Network & internet',fill='black')
        d.rounded_rectangle((25,105,240,155),radius=8,fill='#f0f0f0',outline='black')
        d.text((45,122),'Wi-Fi',fill='black')
        d.text((25,185),'Bluetooth',fill='black')
        d.text((250,122),'Connected',fill='black')
    p=Path('/tmp/'+kind+'.jpg'); img.save(p,'JPEG',quality=85); return base64.b64encode(p.read_bytes()).decode()

IMAGES={t['name']:make_image('continue' if t['name']=='continue_button' else 'wifi') for t in TASKS}

def call(model,messages):
    body={'model':model,'messages':messages,'temperature':0,'max_tokens':256}
    req=Request(BASE,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+KEY,'Content-Type':'application/json','HTTP-Referer':'https://github.com/mhommdkuyr/Universal-Creative-Agent','X-Title':'UCOA provider benchmark'},method='POST')
    started=time.perf_counter()
    try:
        with urlopen(req,timeout=20) as r: data=json.loads(r.read().decode())
    except Exception as e:
        raise RuntimeError(str(e)[:300])
    elapsed=round((time.perf_counter()-started)*1000,2)
    usage=data.get('usage') or {}
    text=(data.get('choices') or [{}])[0].get('message',{}).get('content','')
    if isinstance(text,list): text=''.join(str(x.get('text','') if isinstance(x,dict) else x) for x in text)
    return str(text),usage,elapsed

def parse_json(text):
    s=text.strip()
    if s.startswith('```'):
        parts=s.split('\n',1)
        s=parts[1] if len(parts)==2 else s
        s=s.rsplit('```',1)[0]
    try: return json.loads(s)
    except Exception: return None

def cost(model,usage,pricing):
    p=pricing.get(model) or {}
    a=float(p.get('prompt',0) or 0); b=float(p.get('completion',0) or 0)
    i=usage.get('prompt_tokens'); o=usage.get('completion_tokens')
    if i is None or o is None: return None
    return (i*a+o*b)/1000000.0

def has_target(obj,target):
    raw=json.dumps(obj,ensure_ascii=False) if not isinstance(obj,str) else obj
    return target.lower() in raw.lower()

def main(out_file,catalog_file):
    catalog=json.loads(Path(catalog_file).read_text(encoding='utf-8'))
    model_rows={m.get('id'):m for m in catalog.get('models',[]) if m.get('id')}
    vision=[m for m in VISION_MODELS if m in model_rows and 'image' in ((model_rows[m].get('architecture') or {}).get('input_modalities') or [])]
    decision=[m for m in DECISION_MODELS if m in model_rows]
    results=[]
    for task in TASKS:
        img=IMAGES[task['name']]
        observations={}
        for vm in vision:
            msgs=[
              {'role':'system','content':'You are UCOA visual perception. Inspect only the supplied screenshot. Return JSON with screen_summary, elements, visible_goal_state, confidence.'},
              {'role':'user','content':[{'type':'text','text':task['instruction']},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+img}}]}
            ]
            try:
                txt,usage,lat=call(vm,msgs); obj=parse_json(txt) or {'raw':txt[:2000]}; observations[vm]={'obj':obj,'txt':txt,'usage':usage,'lat':lat,'ok':has_target(obj,task['target'])}
            except Exception as e:
                observations[vm]={'error':str(e)}
        for vm,vo in observations.items():
            if 'error' in vo:
                for dm in decision:
                    results.append({'task':task['name'],'vision_model':vm,'decision_model':dm,'vision_ok':False,'decision_ok':False,'pair_ok':False,'error':'VISION:'+vo['error']})
                continue
            for dm in decision:
                payload={'task':task['instruction'],'visual_observation':vo['obj'],'target':task['target']}
                msgs=[
                  {'role':'system','content':'You are UCOA Android controller. Return ONLY JSON with action, params, verification_goal, confidence. For a visible textual target, use action click_any_text with params texts containing the exact target.'},
                  {'role':'user','content':json.dumps(payload,ensure_ascii=False)}
                ]
                try:
                    dt,du,dl=call(dm,msgs); dobj=parse_json(dt) or {'raw':dt[:2000]}
                    action=str(dobj.get('action','')).lower() if isinstance(dobj,dict) else ''
                    params=dobj.get('params',{}) if isinstance(dobj,dict) else {}
                    texts=params.get('texts',[]) if isinstance(params,dict) else []
                    if isinstance(texts,str): texts=[texts]
                    dok=action=='click_any_text' and any(str(x).strip().lower()==task['target'].lower() for x in texts)
                    vc=cost(vm,vo['usage'],{k:(v.get('pricing') or {}) for k,v in model_rows.items()})
                    dc=cost(dm,du,{k:(v.get('pricing') or {}) for k,v in model_rows.items()})
                    results.append({'task':task['name'],'vision_model':vm,'decision_model':dm,'vision_ok':vo['ok'],'decision_ok':dok,'pair_ok':vo['ok'] and dok,'vision_latency_ms':vo['lat'],'decision_latency_ms':dl,'total_latency_ms':round(vo['lat']+dl,2),'vision_usage':vo['usage'],'decision_usage':du,'vision_cost_usd':vc,'decision_cost_usd':dc,'pair_cost_usd':(vc or 0)+(dc or 0),'vision_text':vo['txt'][:1200],'decision_text':dt[:1200],'decision_json':dobj})
                except Exception as e:
                    results.append({'task':task['name'],'vision_model':vm,'decision_model':dm,'error':str(e)[:300]})
    summary={}
    for r in results:
        k=r['vision_model']+' + '+r['decision_model']
        q=summary.setdefault(k,{'vision_model':r['vision_model'],'decision_model':r['decision_model'],'tasks':0,'successes':0,'latencies':[],'costs':[]})
        q['tasks']+=1
        if r.get('pair_ok'): q['successes']+=1
        if r.get('total_latency_ms') is not None: q['latencies'].append(r['total_latency_ms'])
        if r.get('pair_cost_usd') is not None: q['costs'].append(r['pair_cost_usd'])
    pairs=[]
    for q in summary.values():
        q['accuracy']=q['successes']/q['tasks'] if q['tasks'] else 0
        q['avg_latency_ms']=sum(q['latencies'])/len(q['latencies']) if q['latencies'] else None
        q['avg_cost_usd']=sum(q['costs'])/len(q['costs']) if q['costs'] else None
        pairs.append(q)
    pairs.sort(key=lambda x:(-x['accuracy'],x['avg_latency_ms'] if x['avg_latency_ms'] is not None else 1e99,x['avg_cost_usd'] if x['avg_cost_usd'] is not None else 1e99))
    Path(out_file).write_text(json.dumps({'vision_models':vision,'decision_models':decision,'tasks':TASKS,'pairs':pairs,'raw_results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'vision_models':vision,'decision_models':decision,'pairs':len(pairs)},ensure_ascii=False))

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--out',default='provider-benchmark.json'); ap.add_argument('--catalog',default='provider-discovery.json'); args=ap.parse_args(); main(args.out,args.catalog)