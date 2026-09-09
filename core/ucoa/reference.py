from __future__ import annotations
import json
import math
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from .models import ReferenceInsight

class ReferenceAnalyzer:
    """Deterministic local media inspection. Remote sources remain explicit/pending."""
    def analyze(self, source: str, media_type: str) -> ReferenceInsight:
        if media_type == "video" and self._is_local_video(source): return self._analyze_local_video(source)
        if media_type == "image" and self._is_local_image(source): return self._analyze_local_image(source)
        host = urlparse(source).netloc or source
        return ReferenceInsight(source=source, media_type=media_type, style={"analysis_status": "remote_source_pending", "source_host": host}, audio={"analysis_status": "pending"} if media_type == "video" else {})

    @staticmethod
    def _is_local_video(source: str) -> bool:
        return Path(source).is_file() and Path(source).suffix.lower() in {'.mp4','.mov','.mkv','.webm','.m4v','.avi'}
    @staticmethod
    def _is_local_image(source: str) -> bool:
        return Path(source).is_file() and Path(source).suffix.lower() in {'.png','.jpg','.jpeg','.webp'}

    def _analyze_local_video(self, source: str) -> ReferenceInsight:
        meta = self._ffprobe(source); duration=float(meta.get('duration') or 0); w=int(meta.get('width') or 0); h=int(meta.get('height') or 0)
        scenes=self._sample_scenes(source,duration)
        return ReferenceInsight(source, 'video', duration, scenes, {'width':w,'height':h,'aspect_ratio':f'{w}:{h}' if w and h else 'unknown','fps':meta.get('fps',0),'pace':'fast' if len(scenes)>=8 else 'medium' if len(scenes)>=4 else 'slow'}, {'streams':meta.get('audio_streams',0),'codec':meta.get('audio_codec')})

    def _analyze_local_image(self, source: str) -> ReferenceInsight:
        from PIL import Image
        import numpy as np
        img=Image.open(source).convert('RGB'); arr=np.asarray(img); avg=arr.reshape(-1,3).mean(axis=0); color='#%02x%02x%02x'%tuple(int(x) for x in avg)
        return ReferenceInsight(source,'image',style={'width':img.width,'height':img.height,'aspect_ratio':f'{img.width}:{img.height}','dominant_average_color':color},scenes=[{'layout':'full_canvas'}])

    def _ffprobe(self, source: str) -> dict:
        raw=subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',source],text=True)
        data=json.loads(raw); fmt=data.get('format',{}); streams=data.get('streams',[]); video=next((s for s in streams if s.get('codec_type')=='video'),{}); audio=next((s for s in streams if s.get('codec_type')=='audio'),{})
        return {'duration':fmt.get('duration'),'audio_streams':sum(1 for s in streams if s.get('codec_type')=='audio'),'width':video.get('width'),'height':video.get('height'),'fps':self._parse_rate(video.get('r_frame_rate')),'audio_codec':audio.get('codec_name')}
    @staticmethod
    def _parse_rate(value):
        try:
            n,d=value.split('/'); return float(n)/float(d)
        except Exception:return 0.0
    def _sample_scenes(self, source, duration):
        if duration<=0:return []
        try:
            import cv2
            cap=cv2.VideoCapture(source); count=max(2,min(12,int(math.ceil(duration/4.0)))); times=[duration*i/count for i in range(count)]; out=[]; prev=None
            for t in times:
                cap.set(cv2.CAP_PROP_POS_MSEC,t*1000); ok,frame=cap.read()
                if not ok: continue
                gray=cv2.cvtColor(cv2.resize(frame,(64,64)),cv2.COLOR_BGR2GRAY); change=None if prev is None else float(cv2.absdiff(gray,prev).mean())/255.0; prev=gray
                out.append({'start':round(t,3),'end':round(min(duration,t+duration/count),3),'visual_change':round(change or 0,4),'brightness':round(float(gray.mean())/255,4),'shot':'high_change' if change is not None and change>=0.16 else 'continuous'})
            cap.release(); return out
        except Exception:return []
